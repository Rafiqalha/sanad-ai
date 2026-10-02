from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
import os
import re
from urllib.parse import quote

import httpx

from .mediawiki import _BoundedTTLCache
from .openalex import _public_http_url, canonical_doi_url, normalise_doi


@dataclass(frozen=True, slots=True)
class CrossrefWork:
    """Crossref bibliographic metadata; Crossref is not a full-text provider."""

    title: str
    authors: tuple[str, ...]
    publisher: str | None
    journal: str | None
    publication_year: int | None
    publication_date: str | None
    doi: str | None
    canonical_doi_url: str | None
    source_url: str
    work_type: str | None
    abstract: str | None
    validation_method: str
    retrieved_at: datetime
    provider_id: str = "crossref"
    provider: str = "Crossref"
    source_class: str = "ACADEMIC"
    authority_scope: str = "BIBLIOGRAPHIC_METADATA_NOT_FULL_TEXT"

    @property
    def year(self) -> int | None:
        return self.publication_year


def _plain_abstract(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    plain = re.sub(r"<[^>]+>", " ", unescape(value))
    plain = " ".join(plain.split()).strip()
    return plain[:3000] or None


def _date_parts(raw: dict[str, object]) -> tuple[int | None, str | None]:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        value = raw.get(key)
        if not isinstance(value, dict):
            continue
        parts = value.get("date-parts")
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
            continue
        components = parts[0]
        if not components or not isinstance(components[0], int):
            continue
        year = components[0]
        if not 500 <= year <= 3000:
            continue
        valid_components = [year]
        if len(components) > 1 and isinstance(components[1], int) and 1 <= components[1] <= 12:
            valid_components.append(components[1])
            if len(components) > 2 and isinstance(components[2], int) and 1 <= components[2] <= 31:
                valid_components.append(components[2])
        publication_date = "-".join(
            [str(valid_components[0])]
            + [f"{component:02d}" for component in valid_components[1:]]
        )
        return year, publication_date
    created = raw.get("created")
    if isinstance(created, dict):
        date_time = str(created.get("date-time") or "").strip()
        match = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", date_time)
        if match:
            year = int(match.group(1))
            if 500 <= year <= 3000:
                return year, "-".join(part for part in match.groups() if part)
    return None, None


def _first_text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


class CrossrefProvider:
    """Polite, keyless Crossref search and exact DOI metadata validation."""

    endpoint = "https://api.crossref.org/works"
    provider_id = "crossref"

    def __init__(
        self,
        *,
        mailto: str | None = None,
        user_agent: str | None = None,
        timeout: float = 10.0,
        max_results: int = 5,
        cache_ttl_seconds: int = 900,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._mailto = mailto if mailto is not None else os.getenv("CROSSREF_MAILTO")
        self._user_agent = (
            user_agent
            or os.getenv("CROSSREF_USER_AGENT")
            or "SANAD.AI/0.2"
        )
        self.timeout = max(0.5, min(float(timeout), 30.0))
        self.max_results = max(1, min(int(max_results), 10))
        self._transport = transport
        self._search_cache: _BoundedTTLCache[list[CrossrefWork]] = _BoundedTTLCache(
            ttl_seconds=cache_ttl_seconds,
            max_items=128,
        )
        self._doi_cache: _BoundedTTLCache[CrossrefWork | None] = _BoundedTTLCache(
            ttl_seconds=cache_ttl_seconds,
            max_items=256,
        )
        self.last_errors: list[str] = []
        self.request_count = 0
        self.cache_hits = 0
        self.cache_misses = 0

    async def search(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[CrossrefWork]:
        query = " ".join(query.split()).strip()
        self._reset_telemetry()
        if not query:
            return []

        bounded_limit = max(1, min(int(limit or self.max_results), self.max_results, 10))
        cache_key = f"search:{bounded_limit}:{query.casefold()}"
        cached, cache_hit = await self._search_cache.get(cache_key)
        if cache_hit and cached is not None:
            self.cache_hits = 1
            return cached
        self.cache_misses = 1

        params: dict[str, object] = {
            "query.bibliographic": query,
            "rows": bounded_limit,
        }
        if self._mailto:
            params["mailto"] = self._mailto
        try:
            payload = await self._get_json(self.endpoint, params=params)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self.last_errors.append(f"Crossref search failed: {type(exc).__name__}.")
            return []

        message = payload.get("message", {}) if isinstance(payload, dict) else {}
        raw_items = message.get("items", []) if isinstance(message, dict) else []
        retrieved_at = datetime.now(timezone.utc)
        works: list[CrossrefWork] = []
        seen: set[str] = set()
        for raw in raw_items[:bounded_limit]:
            work = self._parse_work(raw, retrieved_at, validation_method="SEARCH")
            if work is None:
                continue
            key = work.doi or work.source_url.casefold()
            if key in seen:
                continue
            seen.add(key)
            works.append(work)
        await self._search_cache.set(cache_key, works)
        return works

    async def lookup_doi(self, doi: str) -> CrossrefWork | None:
        self._reset_telemetry()
        clean_doi = normalise_doi(doi)
        if clean_doi is None:
            self.last_errors.append("Crossref DOI validation skipped: invalid DOI.")
            return None

        cache_key = f"doi:{clean_doi}"
        cached, cache_hit = await self._doi_cache.get(cache_key)
        if cache_hit:
            self.cache_hits = 1
            return cached
        self.cache_misses = 1

        params = {"mailto": self._mailto} if self._mailto else None
        url = f"{self.endpoint}/{quote(clean_doi, safe='')}"
        try:
            payload = await self._get_json(url, params=params)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            self.last_errors.append(f"Crossref DOI validation returned HTTP {status}.")
            await self._doi_cache.set(cache_key, None)
            return None
        except (httpx.RequestError, ValueError, TypeError) as exc:
            self.last_errors.append(
                f"Crossref DOI validation failed: {type(exc).__name__}."
            )
            return None

        message = payload.get("message") if isinstance(payload, dict) else None
        work = self._parse_work(
            message,
            datetime.now(timezone.utc),
            validation_method="DOI_LOOKUP",
        )
        # Exact endpoint metadata must identify the requested DOI.
        if work is None or work.doi != clean_doi:
            self.last_errors.append("Crossref DOI validation returned mismatched metadata.")
            work = None
        await self._doi_cache.set(cache_key, work)
        return work

    async def validate_doi(self, doi: str) -> CrossrefWork | None:
        return await self.lookup_doi(doi)

    async def retrieve(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[CrossrefWork]:
        return await self.search(query, limit=limit)

    def _reset_telemetry(self) -> None:
        self.last_errors = []
        self.request_count = 0
        self.cache_hits = 0
        self.cache_misses = 0

    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, object] | None,
    ) -> object:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            transport=self._transport,
            headers={
                "Accept": "application/json",
                "User-Agent": self._user_agent,
            },
        ) as client:
            response = await client.get(url, params=params)
        self.request_count += 1
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _parse_work(
        raw: object,
        retrieved_at: datetime,
        *,
        validation_method: str,
    ) -> CrossrefWork | None:
        if not isinstance(raw, dict):
            return None
        title = _first_text(raw.get("title"))
        if not title:
            return None

        authors: list[str] = []
        for author in raw.get("author") or []:
            if not isinstance(author, dict):
                continue
            literal = str(author.get("name") or "").strip()
            given = str(author.get("given") or "").strip()
            family = str(author.get("family") or "").strip()
            name = literal or " ".join(part for part in (given, family) if part)
            if name and name.casefold() not in {item.casefold() for item in authors}:
                authors.append(name)

        doi = normalise_doi(raw.get("DOI") or raw.get("doi"))
        doi_url = canonical_doi_url(doi)
        provider_url = _public_http_url(raw.get("URL") or raw.get("url"))
        source_url = doi_url or provider_url
        if source_url is None:
            return None

        year, publication_date = _date_parts(raw)
        return CrossrefWork(
            title=title,
            authors=tuple(authors),
            publisher=(str(raw.get("publisher") or "").strip() or None),
            journal=_first_text(raw.get("container-title")),
            publication_year=year,
            publication_date=publication_date,
            doi=doi,
            canonical_doi_url=doi_url,
            source_url=source_url,
            work_type=(str(raw.get("type") or "").strip() or None),
            abstract=_plain_abstract(raw.get("abstract")),
            validation_method=validation_method,
            retrieved_at=retrieved_at,
        )


CrossrefClient = CrossrefProvider
