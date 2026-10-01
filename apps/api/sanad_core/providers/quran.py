from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
import hashlib
import json
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from ..config import settings
from ..quran_reference import (
    QuranReferenceHint,
    detect_exact_reference,
    resolve_chapter,
)
from ..schemas import Candidate, QueryBundle, RetrievalMode, SourceClass
from .base import QuranEvidenceProvider
from .broad_web import AsyncTTLCache


_ENVIRONMENTS = {
    "prelive": {
        "auth": "https://prelive-oauth2.quran.foundation",
        "gateway": "https://apis-prelive.quran.foundation",
    },
    "production": {
        "auth": "https://oauth2.quran.foundation",
        "gateway": "https://apis.quran.foundation",
    },
}
_VERSE_KEY = re.compile(
    r"^(?P<chapter>[1-9]|[1-9]\d|1[01]\d|11[0-4]):(?P<verse>[1-9]\d{0,2})$"
)
_HTML_TAG = re.compile(r"<[^>]+>")


class QuranProviderError(RuntimeError):
    """Sanitized Quran Foundation provider error."""


class QuranProviderUnavailable(QuranProviderError):
    """Raised when server-side Quran Foundation credentials are absent."""


@dataclass(frozen=True)
class TranslationResource:
    resource_id: int
    name: str
    language_name: str


@dataclass
class QuranProviderResult:
    candidates: list[Candidate]
    mode: RetrievalMode
    errors: list[str] = field(default_factory=list)


def _clean_provider_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    # Translation payloads can contain provider-supplied formatting/footnote
    # tags. The UI renders plain text and never interprets this as HTML.
    return " ".join(unescape(_HTML_TAG.sub(" ", value)).split()).strip() or None


def _unique_errors(errors: list[str]) -> list[str]:
    """Keep provider diagnostics useful when parallel query variants fail alike."""

    return list(dict.fromkeys(error for error in errors if error))


class _TokenManager:
    def __init__(
        self,
        *,
        auth_base: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.auth_base = auth_base
        self._transport = transport
        self._tokens: dict[str, tuple[str, float]] = {}
        self._failures: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    def invalidate(self, scope: str) -> None:
        self._tokens.pop(scope, None)
        self._failures.pop(scope, None)

    async def get(self, scope: str) -> str:
        cached = self._tokens.get(scope)
        now = time.monotonic()
        if cached and cached[1] > now:
            return cached[0]
        failed = self._failures.get(scope)
        if failed and failed[1] > now:
            raise QuranProviderError(failed[0])

        async with self._lock:
            cached = self._tokens.get(scope)
            now = time.monotonic()
            if cached and cached[1] > now:
                return cached[0]
            failed = self._failures.get(scope)
            if failed and failed[1] > now:
                raise QuranProviderError(failed[0])

            client_id = settings.quran_foundation_client_id
            client_secret = settings.quran_foundation_client_secret
            if not client_id or not client_secret:
                raise QuranProviderUnavailable(
                    "Quran Foundation credentials are not configured."
                )

            try:
                async with httpx.AsyncClient(
                    timeout=settings.sanad_http_timeout,
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    response = await client.post(
                        f"{self.auth_base}/oauth2/token",
                        auth=httpx.BasicAuth(client_id, client_secret),
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        data={
                            "grant_type": "client_credentials",
                            "scope": scope,
                        },
                    )
            except httpx.RequestError as exc:
                raise QuranProviderError(
                    f"Quran Foundation token request failed: {type(exc).__name__}."
                ) from None

            if response.status_code != 200:
                detail = ""
                try:
                    failure_payload = response.json()
                except ValueError:
                    failure_payload = None
                if isinstance(failure_payload, dict):
                    error_code = str(
                        failure_payload.get("error")
                        or failure_payload.get("type")
                        or ""
                    ).strip()
                    if error_code:
                        detail = f" ({error_code[:80]})"
                message = (
                    "Quran Foundation token request returned HTTP "
                    f"{response.status_code}{detail}."
                )
                if response.status_code in {400, 403}:
                    self._failures[scope] = (message, now + 60.0)
                raise QuranProviderError(message)
            try:
                payload = response.json()
            except ValueError:
                raise QuranProviderError(
                    "Quran Foundation token response was invalid JSON."
                ) from None
            token = payload.get("access_token") if isinstance(payload, dict) else None
            expires_in = payload.get("expires_in", 3600) if isinstance(payload, dict) else 0
            if not isinstance(token, str) or not token.strip():
                raise QuranProviderError(
                    "Quran Foundation token response omitted access_token."
                )
            returned_scope = payload.get("scope") if isinstance(payload, dict) else None
            if isinstance(returned_scope, str) and returned_scope.strip():
                granted_scopes = set(returned_scope.split())
                if scope not in granted_scopes:
                    raise QuranProviderError(
                        "Quran Foundation token does not grant the requested scope."
                    )
            try:
                lifetime = max(1.0, float(expires_in))
            except (TypeError, ValueError):
                lifetime = 3600.0
            # Renew early; client-credentials has no refresh token.
            self._tokens[scope] = (token.strip(), now + max(1.0, lifetime - 60.0))
            self._failures.pop(scope, None)
            return token.strip()


class QuranProvider(QuranEvidenceProvider):
    """Official Quran Foundation Search + Content API adapter.

    Exact references are resolved against provider chapter metadata. Semantic
    searches return verse keys from Search API, then hydrate every candidate via
    Content API. No phrase-to-verse lookup table exists in this adapter.
    """

    provider_id = "quran_foundation"

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        environment: str | None = None,
        cache: AsyncTTLCache[QuranProviderResult] | None = None,
    ):
        self._transport = transport
        self.environment = environment or settings.quran_foundation_env
        if self.environment not in _ENVIRONMENTS:
            raise ValueError("Unsupported Quran Foundation environment.")
        env = _ENVIRONMENTS[self.environment]
        self.auth_base = env["auth"]
        self.gateway_base = env["gateway"]
        self._tokens = _TokenManager(
            auth_base=self.auth_base,
            transport=self._transport,
        )
        self._chapters: list[dict[str, Any]] | None = None
        self._indonesian_translation: TranslationResource | None | bool = False
        self._result_cache = cache or AsyncTTLCache(
            ttl_seconds=settings.sanad_knowledge_cache_ttl_seconds
        )

    @property
    def configured(self) -> bool:
        return bool(
            settings.quran_foundation_client_id
            and settings.quran_foundation_client_secret
        )

    async def _request(
        self,
        *,
        scope: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise QuranProviderUnavailable(
                "Quran Foundation credentials are not configured."
            )

        for attempt in range(3):
            token = await self._tokens.get(scope)
            headers = {
                "x-auth-token": token,
                "x-client-id": settings.quran_foundation_client_id or "",
                "Accept": "application/json",
            }
            try:
                async with httpx.AsyncClient(
                    timeout=settings.sanad_http_timeout,
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    response = await client.get(
                        f"{self.gateway_base}{path}",
                        headers=headers,
                        params=params,
                    )
            except httpx.RequestError as exc:
                raise QuranProviderError(
                    f"Quran Foundation {scope} request failed: {type(exc).__name__}."
                ) from None

            if response.status_code == 401 and attempt == 0:
                self._tokens.invalidate(scope)
                continue
            if (
                response.status_code == 429
                or 500 <= response.status_code < 600
            ) and attempt < 2:
                retry_after = response.headers.get("retry-after", "")
                try:
                    delay = min(1.0, max(0.05, float(retry_after)))
                except (TypeError, ValueError):
                    delay = 0.15 * (attempt + 1)
                await asyncio.sleep(delay)
                continue
            if response.status_code != 200:
                raise QuranProviderError(
                    f"Quran Foundation {scope} API returned HTTP "
                    f"{response.status_code}."
                )
            try:
                payload = response.json()
            except ValueError:
                raise QuranProviderError(
                    f"Quran Foundation {scope} API returned invalid JSON."
                ) from None
            if not isinstance(payload, dict):
                raise QuranProviderError(
                    f"Quran Foundation {scope} API returned a non-object payload."
                )
            return payload

        raise QuranProviderError("Quran Foundation authentication retry failed.")

    async def list_chapters(self) -> list[dict[str, Any]]:
        if self._chapters is not None:
            return self._chapters
        payload = await self._request(
            scope="content",
            path="/content/api/v4/chapters",
            params={"language": "id"},
        )
        chapters = payload.get("chapters")
        if not isinstance(chapters, list) or not all(
            isinstance(chapter, dict) for chapter in chapters
        ):
            raise QuranProviderError(
                "Quran Foundation chapters response is malformed."
            )
        self._chapters = chapters
        return chapters

    async def get_indonesian_translation(self) -> TranslationResource | None:
        if self._indonesian_translation is not False:
            return self._indonesian_translation

        payload = await self._request(
            scope="content",
            path="/content/api/v4/resources/translations",
            params={"language": "id"},
        )
        resources = payload.get("translations")
        if not isinstance(resources, list):
            raise QuranProviderError(
                "Quran Foundation translation resources response is malformed."
            )

        selected: TranslationResource | None = None
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            language_name = str(resource.get("language_name") or "").strip()
            translated_name = resource.get("translated_name")
            language_keys = {
                value.casefold().replace("_", " ").replace("-", " ")
                # translated_name is a localized display label, not the
                # language of the translation content itself.
                for value in (language_name,)
                if value
            }
            is_indonesian = bool(
                language_keys
                & {"indonesian", "bahasa indonesia", "indonesia", "id"}
            )
            try:
                resource_id = int(resource.get("id"))
            except (TypeError, ValueError):
                continue
            if not is_indonesian or resource_id <= 0:
                continue
            translated_label = (
                str(translated_name.get("name") or "").strip()
                if isinstance(translated_name, dict)
                else ""
            )
            name = (
                str(resource.get("name") or "").strip()
                or translated_label
                or f"Resource {resource_id}"
            )
            selected = TranslationResource(resource_id, name, language_name or "Indonesian")
            break

        self._indonesian_translation = selected
        return selected

    async def _search_verse_keys(
        self,
        query: str,
        translation: TranslationResource | None,
        *,
        constrain_to_translation: bool,
    ) -> list[str]:
        params: dict[str, Any] = {
            "mode": "advanced",
            "query": query,
            "page": 1,
            "size": settings.sanad_quran_max_results,
            "get_text": "0",
            "highlight": "0",
        }
        # The provider's current Search contract uses translation_ids as the
        # indexed translation corpus. Keep the dynamically selected Indonesian
        # resource attached to all variants; Arabic text search remains a
        # supplemental attempt and final content is always hydrated separately.
        if translation is not None:
            params["translation_ids"] = str(translation.resource_id)
        payload = await self._request(
            scope="search",
            path="/search/api/v1/search",
            params=params,
        )
        result = payload.get("result")
        verses = result.get("verses") if isinstance(result, dict) else None
        if not isinstance(verses, list):
            raise QuranProviderError("Quran Foundation search response is malformed.")
        keys: list[str] = []
        for item in verses:
            if not isinstance(item, dict) or item.get("result_type") != "ayah":
                continue
            key = item.get("key")
            if isinstance(key, str) and _VERSE_KEY.fullmatch(key.strip()):
                keys.append(key.strip())
        return list(dict.fromkeys(keys))

    async def _fetch_verse(
        self,
        verse_key: str,
        *,
        chapter_name: str,
        translation: TranslationResource | None,
        retrieval_mode: RetrievalMode,
        retrieval_queries: list[str],
    ) -> Candidate:
        match = _VERSE_KEY.fullmatch(verse_key)
        if match is None:
            raise QuranProviderError("Search API returned an invalid verse key.")
        params: dict[str, Any] = {
            "language": "id",
            "words": "false",
            "fields": "text_uthmani",
            "translation_fields": "resource_name,language_name",
        }
        if translation is not None:
            params["translations"] = str(translation.resource_id)

        payload = await self._request(
            scope="content",
            path=f"/content/api/v4/verses/by_key/{quote(verse_key, safe=':')}",
            params=params,
        )
        verse = payload.get("verse")
        if not isinstance(verse, dict):
            raise QuranProviderError("Quran Foundation verse response is malformed.")
        returned_key = str(verse.get("verse_key") or "").strip()
        if returned_key != verse_key:
            raise QuranProviderError(
                "Quran Foundation verse response does not match the requested key."
            )
        try:
            # Content API v4 currently omits chapter_id on by_key responses;
            # the already validated returned verse_key is the canonical source
            # for the chapter component in that case.
            chapter_number = int(
                verse.get("chapter_id") or match.group("chapter")
            )
            verse_number = int(verse.get("verse_number"))
        except (TypeError, ValueError):
            raise QuranProviderError(
                "Quran Foundation verse response omitted numeric identity."
            ) from None
        if (
            chapter_number != int(match.group("chapter"))
            or verse_number != int(match.group("verse"))
        ):
            raise QuranProviderError(
                "Quran Foundation verse metadata conflicts with the verse key."
            )
        arabic = _clean_provider_text(verse.get("text_uthmani"))
        if not arabic:
            raise QuranProviderError(
                "Quran Foundation verse response omitted Arabic text."
            )

        translation_text: str | None = None
        translations = verse.get("translations")
        if translation is not None and isinstance(translations, list):
            for item in translations:
                if not isinstance(item, dict):
                    continue
                try:
                    resource_id = int(item.get("resource_id"))
                except (TypeError, ValueError):
                    continue
                if resource_id == translation.resource_id:
                    translation_text = _clean_provider_text(item.get("text"))
                    break

        identifier = f"quran:{verse_key}"
        candidate_hash = hashlib.sha1(identifier.encode("utf-8")).hexdigest()[:16]
        texts = {"ar": arabic}
        if translation_text:
            texts["id"] = translation_text

        return Candidate(
            candidate_id=f"quran-{candidate_hash}",
            provider_id=self.provider_id,
            provider_name="Quran Foundation",
            source_type="quran_canonical",
            trust_tier=1,
            title=f"Surah {chapter_name} {verse_key}",
            collection=chapter_name,
            item_number=str(verse_number),
            language="ar+id" if translation_text else "ar",
            retrieved_text=translation_text or arabic,
            retrieved_texts=texts,
            surah_name=chapter_name,
            surah_number=chapter_number,
            verse_number=verse_number,
            verse_key=verse_key,
            translation_name=translation.name if translation else None,
            retrieval_mode=retrieval_mode,
            # Quran.com documents a chapter/verse route. It is derived only
            # from the Content API verse key and still receives a separate
            # liveness and identity check before the UI may expose it.
            source_url=(
                f"https://quran.com/{chapter_number}/{verse_number}"
            ),
            source_domain="quran.com",
            page_title=f"Surah {chapter_name} {verse_key}",
            source_class=SourceClass.PRIMARY_RELIGIOUS_SOURCE,
            retrieved_at=datetime.now(timezone.utc),
            source_identifier=identifier,
            retrieval_queries=list(dict.fromkeys(retrieval_queries)),
            metadata_complete=True,
            provider_api_validated=True,
            canonical_provider_validated=True,
            official_api_validated=False,
            raw={
                "verse_key": verse_key,
                "chapter_id": chapter_number,
                "verse_number": verse_number,
                "translation_resource_id": (
                    translation.resource_id if translation else None
                ),
                "translation_resource_name": (
                    translation.name if translation else None
                ),
                "translation_language": (
                    translation.language_name if translation else None
                ),
                "translation_state": (
                    "PROVIDER_INDONESIAN"
                    if translation_text
                    else "INDONESIAN_PROVIDER_TRANSLATION_UNAVAILABLE"
                ),
                "canonical_url_rule": "QURAN_COM_CHAPTER_VERSE",
                "quran_foundation_environment": self.environment,
            },
        )

    async def retrieve(
        self,
        source_text: str,
        queries: QueryBundle,
    ) -> QuranProviderResult:
        if not self.configured:
            raise QuranProviderUnavailable(
                "Quran Foundation credentials are not configured."
            )

        cache_key = json.dumps(
            {
                "environment": self.environment,
                "source_text": " ".join(source_text.casefold().split()),
                "queries": queries.all_queries,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        cached, cache_hit = await self._result_cache.get(cache_key)
        if cache_hit and cached is not None:
            return cached

        hint = detect_exact_reference(source_text)
        errors: list[str] = []
        chapters = await self.list_chapters()
        try:
            translation = await self.get_indonesian_translation()
        except QuranProviderError as exc:
            translation = None
            errors.append(
                "Resource terjemahan Bahasa Indonesia Quran Foundation tidak "
                f"dapat diakses: {exc}"
            )
        if translation is None:
            errors.append(
                "Quran Foundation tidak mengembalikan resource terjemahan "
                "Bahasa Indonesia; sistem tidak membuat terjemahan sendiri."
            )

        if hint is not None:
            try:
                chapter_number, chapter_name, _ = resolve_chapter(hint, chapters)
            except ValueError as exc:
                return QuranProviderResult(
                    candidates=[],
                    mode=RetrievalMode.EXACT_REFERENCE,
                    errors=[str(exc)],
                )
            verse_key = f"{chapter_number}:{hint.verse_number}"
            candidate = await self._fetch_verse(
                verse_key,
                chapter_name=chapter_name,
                translation=translation,
                retrieval_mode=RetrievalMode.EXACT_REFERENCE,
                retrieval_queries=[source_text],
            )
            result = QuranProviderResult(
                candidates=[candidate],
                mode=RetrievalMode.EXACT_REFERENCE,
                errors=errors,
            )
            await self._result_cache.set(cache_key, result)
            return result

        search_queries: list[tuple[str, bool]] = []
        seen_queries: set[str] = set()
        query_groups = (
            (queries.attribution_neutral_queries, True),
            (queries.indonesian_queries[:2], True),
            (queries.english_queries[:1], False),
            (queries.arabic_queries[:1], False),
        )
        for group, constrain_to_translation in query_groups:
            for query in group:
                query = query.strip()
                key = query.casefold()
                if query and key not in seen_queries:
                    seen_queries.add(key)
                    search_queries.append((query, constrain_to_translation))
        if not search_queries:
            return QuranProviderResult(
                candidates=[],
                mode=RetrievalMode.SEMANTIC_SEARCH,
                errors=errors + ["Tidak ada query Qur'an semantik yang aman."],
            )

        async def search_one(query: str, constrain_to_translation: bool):
            try:
                return query, await self._search_verse_keys(
                    query,
                    translation,
                    constrain_to_translation=constrain_to_translation,
                ), None
            except QuranProviderError as exc:
                return query, [], str(exc)

        search_responses = await asyncio.gather(
            *(search_one(query, constrained) for query, constrained in search_queries)
        )
        queries_by_key: dict[str, list[str]] = {}
        for query, keys, error in search_responses:
            if error:
                errors.append(f"Quran Foundation search gagal: {error}")
                continue
            for key in keys:
                if (
                    key not in queries_by_key
                    and len(queries_by_key) >= settings.sanad_quran_max_results
                ):
                    continue
                queries_by_key.setdefault(key, []).append(query)

        if not queries_by_key:
            return QuranProviderResult(
                candidates=[],
                mode=RetrievalMode.SEMANTIC_SEARCH,
                errors=_unique_errors(errors),
            )

        chapter_names = {
            int(chapter.get("id")): str(chapter.get("name_simple") or "").strip()
            for chapter in chapters
            if isinstance(chapter, dict)
            and str(chapter.get("id") or "").isdigit()
            and str(chapter.get("name_simple") or "").strip()
        }

        async def fetch_one(key: str, key_queries: list[str]):
            chapter_number = int(key.split(":", 1)[0])
            chapter_name = chapter_names.get(chapter_number)
            if not chapter_name:
                return None, f"Metadata surah untuk verse key {key} tidak tersedia."
            try:
                return await self._fetch_verse(
                    key,
                    chapter_name=chapter_name,
                    translation=translation,
                    retrieval_mode=RetrievalMode.SEMANTIC_SEARCH,
                    retrieval_queries=key_queries,
                ), None
            except QuranProviderError as exc:
                return None, f"Quran Foundation content {key} gagal: {exc}"

        fetched = await asyncio.gather(
            *(fetch_one(key, key_queries) for key, key_queries in queries_by_key.items())
        )
        candidates: list[Candidate] = []
        for candidate, error in fetched:
            if error:
                errors.append(error)
            elif candidate is not None:
                candidates.append(candidate)

        result = QuranProviderResult(
            candidates=candidates,
            mode=RetrievalMode.SEMANTIC_SEARCH,
            errors=_unique_errors(errors),
        )
        if candidates:
            await self._result_cache.set(cache_key, result)
        return result
