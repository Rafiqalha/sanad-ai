from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import os
import re
from urllib.parse import urlsplit

import httpx

from .mediawiki import _BoundedTTLCache


_DOI_PREFIX_RE = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
    flags=re.IGNORECASE,
)


def normalise_doi(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    doi = _DOI_PREFIX_RE.sub("", value.strip()).strip().casefold()
    if not doi.startswith("10.") or "/" not in doi or any(char.isspace() for char in doi):
        return None
    return doi.rstrip(".,;)")


def canonical_doi_url(doi: str | None) -> str | None:
    return f"https://doi.org/{doi}" if doi else None


def _public_http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if (
        parts.scheme.casefold() not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in {None, 80, 443}
    ):
        return None
    hostname = parts.hostname.casefold().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return None
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        return None
    return value


def _abstract_from_inverted_index(value: object, *, max_chars: int = 3000) -> str | None:
    if not isinstance(value, dict):
        return None
    positioned_words: list[tuple[int, str]] = []
    for word, positions in value.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                positioned_words.append((position, word))
    if not positioned_words:
        return None
    positioned_words.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positioned_words)[:max_chars].strip() or None


@dataclass(frozen=True, slots=True)
class OpenAlexWork:
    """Scholarly discovery metadata; never a religious-authority assertion."""

    openalex_id: str
    title: str
    authors: tuple[str, ...]
    publication_year: int | None
    publication_date: str | None
    source_name: str | None
    doi: str | None
    canonical_doi_url: str | None
    is_open_access: bool | None
    oa_status: str | None
    oa_url: str | None
    landing_page_url: str
    abstract: str | None
    work_type: str | None
    retrieved_at: datetime
    provider_id: str = "openalex"
    provider: str = "OpenAlex"
    source_class: str = "ACADEMIC"
    authority_scope: str = "SCHOLARLY_DISCOVERY_NOT_RELIGIOUS_AUTHORITY"

    @property
    def year(self) -> int | None:
        return self.publication_year

    @property
    def journal(self) -> str | None:
        return self.source_name

    @property
    def source_url(self) -> str:
        return self.landing_page_url


class OpenAlexProvider:
    """Bounded OpenAlex Works client supporting optional API-key mode."""

    endpoint = "https://api.openalex.org/works"
    provider_id = "openalex"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        mailto: str | None = None,
        timeout: float = 10.0,
        max_results: int = 5,
        cache_ttl_seconds: int = 900,
        transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str | None = None,
    ):
        self._api_key = api_key if api_key is not None else os.getenv("OPENALEX_API_KEY")
        self._mailto = mailto if mailto is not None else os.getenv("OPENALEX_MAILTO")
        self.timeout = max(0.5, min(float(timeout), 30.0))
        self.max_results = max(1, min(int(max_results), 10))
        self._transport = transport
        self._user_agent = (
            user_agent
            or os.getenv("SANAD_USER_AGENT")
            or "SANAD.AI/0.2 (public-source retrieval)"
        )
        self._cache: _BoundedTTLCache[list[OpenAlexWork]] = _BoundedTTLCache(
            ttl_seconds=cache_ttl_seconds,
            max_items=128,
        )
        self.last_errors: list[str] = []
        self.request_count = 0
        self.cache_hits = 0
        self.cache_misses = 0

    @property
    def keyed_mode(self) -> bool:
        return bool(self._api_key)

    async def search(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[OpenAlexWork]:
        query = " ".join(query.split()).strip()
        self.last_errors = []
        self.request_count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        if not query:
            return []

        bounded_limit = max(1, min(int(limit or self.max_results), self.max_results, 10))
        cache_key = f"{bounded_limit}:{query.casefold()}"
        cached, cache_hit = await self._cache.get(cache_key)
        if cache_hit and cached is not None:
            self.cache_hits = 1
            return cached
        self.cache_misses = 1

        params: dict[str, object] = {
            "search": query,
            "per-page": bounded_limit,
        }
        if self._mailto:
            params["mailto"] = self._mailto
        if self._api_key:
            params["api_key"] = self._api_key

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                transport=self._transport,
                headers={"Accept": "application/json", "User-Agent": self._user_agent},
            ) as client:
                response = await client.get(self.endpoint, params=params)
            self.request_count = 1
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            self.last_errors.append(
                "OpenAlex retrieval returned HTTP "
                f"{exc.response.status_code}."
            )
            return []
        except (httpx.RequestError, ValueError, TypeError) as exc:
            self.last_errors.append(f"OpenAlex retrieval failed: {type(exc).__name__}.")
            return []

        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        now = datetime.now(timezone.utc)
        works: list[OpenAlexWork] = []
        seen_ids: set[str] = set()
        for raw in raw_results[:bounded_limit]:
            work = self._parse_work(raw, now)
            if work is None or work.openalex_id.casefold() in seen_ids:
                continue
            seen_ids.add(work.openalex_id.casefold())
            works.append(work)
        await self._cache.set(cache_key, works)
        return works

    async def retrieve(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[OpenAlexWork]:
        return await self.search(query, limit=limit)

    @staticmethod
    def _parse_work(raw: object, retrieved_at: datetime) -> OpenAlexWork | None:
        if not isinstance(raw, dict):
            return None
        openalex_id = _public_http_url(raw.get("id"))
        title = str(raw.get("display_name") or raw.get("title") or "").strip()
        if not openalex_id or not title:
            return None

        authors: list[str] = []
        for authorship in raw.get("authorships") or []:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author") or {}
            name = str(author.get("display_name") or "").strip() if isinstance(author, dict) else ""
            if name and name.casefold() not in {item.casefold() for item in authors}:
                authors.append(name)

        primary_location = raw.get("primary_location") or {}
        if not isinstance(primary_location, dict):
            primary_location = {}
        source = primary_location.get("source") or {}
        if not isinstance(source, dict):
            source = {}
        source_name = str(source.get("display_name") or "").strip() or None

        best_oa_location = raw.get("best_oa_location") or {}
        if not isinstance(best_oa_location, dict):
            best_oa_location = {}
        open_access = raw.get("open_access") or {}
        if not isinstance(open_access, dict):
            open_access = {}

        doi = normalise_doi(raw.get("doi"))
        doi_url = canonical_doi_url(doi)
        primary_landing = _public_http_url(primary_location.get("landing_page_url"))
        best_oa_landing = _public_http_url(best_oa_location.get("landing_page_url"))
        landing_page = primary_landing or doi_url or best_oa_landing or openalex_id
        oa_url = (
            _public_http_url(open_access.get("oa_url"))
            or best_oa_landing
            or _public_http_url(best_oa_location.get("pdf_url"))
        )

        year_value = raw.get("publication_year")
        year = year_value if isinstance(year_value, int) and 500 <= year_value <= 3000 else None
        publication_date = str(raw.get("publication_date") or "").strip() or None
        is_oa_value = open_access.get("is_oa")
        is_open_access = is_oa_value if isinstance(is_oa_value, bool) else None
        oa_status = str(open_access.get("oa_status") or "").strip() or None

        return OpenAlexWork(
            openalex_id=openalex_id,
            title=title,
            authors=tuple(authors),
            publication_year=year,
            publication_date=publication_date,
            source_name=source_name,
            doi=doi,
            canonical_doi_url=doi_url,
            is_open_access=is_open_access,
            oa_status=oa_status,
            oa_url=oa_url,
            landing_page_url=landing_page,
            abstract=_abstract_from_inverted_index(raw.get("abstract_inverted_index")),
            work_type=(str(raw.get("type") or "").strip() or None),
            retrieved_at=retrieved_at,
        )


OpenAlexClient = OpenAlexProvider
