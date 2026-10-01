from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator

from ..config import settings
from ..schemas import Candidate, SourceClass
from .base import CuratedSearchProvider
from .broad_web import AsyncTTLCache


HADITH_API_BOOK_SLUGS = frozenset(
    {
        "sahih-bukhari",
        "sahih-muslim",
        "al-tirmidhi",
        "abu-dawood",
        "ibn-e-majah",
        "sunan-nasai",
        "mishkat",
        "musnad-ahmad",
        "al-silsila-sahiha",
    }
)

_FILTER_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_STATUS_ALIASES = {
    "sahih": "Sahih",
    "hasan": "Hasan",
    "da`eef": "Da`eef",
    "da'eef": "Da`eef",
    "daeef": "Da`eef",
    "daif": "Da`eef",
}


class HadithAPIError(RuntimeError):
    """Sanitized provider error that never includes the API-key query string."""


class HadithAPISearchRequest(BaseModel):
    """Typed representation of the filters documented by HadithAPI."""

    hadith_english: str | None = None
    hadith_arabic: str | None = None
    hadith_number: str | None = None
    book: str | None = None
    chapter: str | None = None
    status: str | None = None
    paginate: int = Field(default=25, ge=1, le=200)

    @field_validator(
        "hadith_english",
        "hadith_arabic",
        "hadith_number",
        "book",
        "chapter",
        "status",
        mode="before",
    )
    @classmethod
    def _strip_optional_strings(cls, value):
        if value is None:
            return None
        normalized = " ".join(str(value).split()).strip()
        return normalized or None

    @field_validator("hadith_number", "chapter")
    @classmethod
    def _validate_reference_filter(cls, value: str | None):
        if value is not None and not _FILTER_COMPONENT.fullmatch(value):
            raise ValueError("HadithAPI number/chapter filter is invalid.")
        return value

    @field_validator("book")
    @classmethod
    def _validate_book(cls, value: str | None):
        if value is None:
            return None
        normalized = value.casefold()
        if normalized not in HADITH_API_BOOK_SLUGS:
            raise ValueError("HadithAPI book filter is not a documented slug.")
        return normalized

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None):
        if value is None:
            return None
        normalized = _STATUS_ALIASES.get(value.casefold())
        if normalized is None:
            raise ValueError("HadithAPI status must be Sahih, Hasan, or Da`eef.")
        return normalized

    @model_validator(mode="after")
    def _require_filter(self):
        if not any(
            (
                self.hadith_english,
                self.hadith_arabic,
                self.hadith_number,
                self.book,
                self.chapter,
                self.status,
            )
        ):
            raise ValueError("At least one HadithAPI search filter is required.")
        return self

    def api_params(self) -> dict[str, str | int]:
        params: dict[str, str | int] = {"paginate": self.paginate}
        field_map = {
            "hadithEnglish": self.hadith_english,
            "hadithArabic": self.hadith_arabic,
            "hadithNumber": self.hadith_number,
            "book": self.book,
            "chapter": self.chapter,
            "status": self.status,
        }
        params.update({key: value for key, value in field_map.items() if value})
        return params

    @property
    def semantic_queries(self) -> list[str]:
        return [q for q in (self.hadith_english, self.hadith_arabic) if q]


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return " ".join(value.split()).strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise HadithAPIError("HadithAPI returned a non-object JSON payload.")

    container = payload.get("hadiths")
    if isinstance(container, dict):
        records = container.get("data")
    elif isinstance(container, list):
        records = container
    elif "data" in payload:
        records = payload.get("data")
    else:
        raise HadithAPIError("HadithAPI response is missing the hadiths collection.")

    if not isinstance(records, list):
        raise HadithAPIError("HadithAPI hadiths collection is not a list.")
    if not all(isinstance(record, dict) for record in records):
        raise HadithAPIError("HadithAPI returned a malformed hadith record.")
    return records


class HadithAPIProvider(CuratedSearchProvider):
    provider_id = "hadithapi"
    # The documented /api/hadiths/ route currently redirects to this canonical
    # application route. Use the canonical HTTPS target directly so the API key
    # is never placed on a redirecting request or forwarded implicitly.
    endpoint = "https://www.hadithapi.com/public/api/hadiths"
    provider_link = "https://www.hadithapi.com/public/api/hadiths"

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: AsyncTTLCache[list[Candidate]] | None = None,
    ):
        self._transport = transport
        self._cache = cache or AsyncTTLCache(
            ttl_seconds=settings.sanad_knowledge_cache_ttl_seconds
        )

    async def search(
        self,
        request: HadithAPISearchRequest,
        retrieval_queries: list[str] | None = None,
    ) -> list[Candidate]:
        if not settings.hadith_api_key:
            raise HadithAPIError("HADITH_API_KEY is not configured.")

        cache_key = json.dumps(
            {
                "filters": request.api_params(),
                "queries": list(dict.fromkeys(retrieval_queries or [])),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        cached, cache_hit = await self._cache.get(cache_key)
        if cache_hit and cached is not None:
            return cached

        params = request.api_params()
        params["apiKey"] = settings.hadith_api_key

        try:
            async with httpx.AsyncClient(
                timeout=settings.sanad_http_timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.get(self.endpoint, params=params)
        except httpx.RequestError as exc:
            raise HadithAPIError(
                f"HadithAPI request failed: {type(exc).__name__}."
            ) from None

        if response.status_code == 404:
            return []
        if response.status_code != 200:
            raise HadithAPIError(
                f"HadithAPI returned HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError:
            raise HadithAPIError("HadithAPI returned invalid JSON.") from None

        queries = list(
            dict.fromkeys((retrieval_queries or []) + request.semantic_queries)
        )
        candidates = self._normalize(payload, request, queries)
        if candidates:
            await self._cache.set(cache_key, candidates)
        return candidates

    def _normalize(
        self,
        payload: Any,
        request: HadithAPISearchRequest,
        retrieval_queries: list[str],
    ) -> list[Candidate]:
        records = _extract_records(payload)
        normalized: dict[str, Candidate] = {}

        for record in records:
            book_obj = record.get("book")
            if not isinstance(book_obj, dict):
                book_obj = {}
            chapter_obj = record.get("chapter")
            if not isinstance(chapter_obj, dict):
                chapter_obj = {}

            book_slug_values = {
                value.casefold()
                for value in (
                    _first_string(record.get("bookSlug")),
                    _first_string(record.get("book_slug")),
                    _first_string(book_obj.get("bookSlug")),
                    _first_string(book_obj.get("book_slug")),
                    _first_string(book_obj.get("slug")),
                )
                if value
            }
            if len(book_slug_values) != 1:
                continue
            book_slug = next(iter(book_slug_values))
            number = _first_string(
                record.get("hadithNumber"),
                record.get("hadith_number"),
                record.get("number"),
            )
            english = _first_string(
                record.get("hadithEnglish"), record.get("hadith_english")
            )
            arabic = _first_string(
                record.get("hadithArabic"), record.get("hadith_arabic")
            )

            # Fail closed for unusable or undocumented collection identifiers.
            if (
                not book_slug
                or book_slug not in HADITH_API_BOOK_SLUGS
                or not number
                or not _FILTER_COMPONENT.fullmatch(number)
                or not (english or arabic)
            ):
                continue

            record_status = _first_string(record.get("status"))
            chapter_number = _first_string(
                record.get("chapterNumber"),
                chapter_obj.get("chapterNumber"),
                record.get("chapterId"),
                chapter_obj.get("id"),
            )

            # Exact structured filters must not be contradicted by the payload.
            if request.book and request.book != book_slug:
                continue
            if request.hadith_number and request.hadith_number != number:
                continue
            if request.chapter and request.chapter != chapter_number:
                continue
            if request.status:
                normalized_status = (
                    _STATUS_ALIASES.get(record_status.casefold())
                    if record_status
                    else None
                )
                if normalized_status != request.status:
                    continue

            identifier = f"hadithapi:{book_slug}:{number}"
            cid = hashlib.sha1(identifier.encode("utf-8")).hexdigest()[:16]
            texts = {
                language: text
                for language, text in (("en", english), ("ar", arabic))
                if text
            }
            book_name = _first_string(
                record.get("bookName"), book_obj.get("bookName"), book_obj.get("name")
            )
            title = _first_string(
                record.get("headingEnglish"),
                record.get("headingArabic"),
                book_name,
            )
            chapter = _first_string(
                record.get("chapterEnglish"),
                chapter_obj.get("chapterEnglish"),
                record.get("chapterArabic"),
                chapter_obj.get("chapterArabic"),
                chapter_number,
            )
            language = "en+ar" if english and arabic else ("en" if english else "ar")

            existing = normalized.get(identifier)
            if existing:
                existing.retrieval_queries = list(
                    dict.fromkeys(existing.retrieval_queries + retrieval_queries)
                )
                continue

            normalized[identifier] = Candidate(
                candidate_id=f"hadithapi-{cid}",
                provider_id=self.provider_id,
                provider_name="HadithAPI",
                source_type="hadith_curated_secondary",
                trust_tier=2,
                title=title,
                collection=book_slug,
                chapter=chapter,
                item_number=number,
                language=language,
                retrieved_text=english or arabic,
                retrieved_texts=texts,
                source_url=self.provider_link,
                source_domain="hadithapi.com",
                source_class=SourceClass.INSTITUTIONAL,
                retrieved_at=datetime.now(timezone.utc),
                source_identifier=identifier,
                retrieval_queries=retrieval_queries,
                metadata_complete=True,
                provider_api_validated=True,
                official_api_validated=False,
                raw={
                    "provider_record_id": record.get("id"),
                    "book_slug": book_slug,
                    "book_name": book_name,
                    "chapter_number": chapter_number,
                    "chapter_english": _first_string(
                        record.get("chapterEnglish"),
                        chapter_obj.get("chapterEnglish"),
                    ),
                    "chapter_arabic": _first_string(
                        record.get("chapterArabic"),
                        chapter_obj.get("chapterArabic"),
                    ),
                    "hadith_number": number,
                    "english_narrator": _first_string(
                        record.get("englishNarrator")
                    ),
                    "status": record_status,
                    "volume": record.get("volume"),
                    "provider_link_kind": "SEARCH_ENDPOINT_NO_DIRECT_ITEM_URL",
                },
            )

        return list(normalized.values())
