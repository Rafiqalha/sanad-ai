from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
import time
from typing import Generic, TypeVar
from urllib.parse import urlsplit

import httpx


_T = TypeVar("_T")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")


class _BoundedTTLCache(Generic[_T]):
    """Small process-local cache; values and credentials never leave memory."""

    def __init__(self, *, ttl_seconds: int = 900, max_items: int = 128):
        self.ttl_seconds = max(1, ttl_seconds)
        self.max_items = max(1, max_items)
        self._items: OrderedDict[str, tuple[float, _T]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> tuple[_T | None, bool]:
        async with self._lock:
            item = self._items.get(key)
            if item is None:
                return None, False
            expires_at, value = item
            if expires_at <= time.monotonic():
                self._items.pop(key, None)
                return None, False
            self._items.move_to_end(key)
            return deepcopy(value), True

    async def set(self, key: str, value: _T) -> None:
        async with self._lock:
            self._items[key] = (time.monotonic() + self.ttl_seconds, deepcopy(value))
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)


@dataclass(frozen=True, slots=True)
class MediaWikiArticle:
    """Actual Wikipedia page extract with explicit encyclopedic provenance."""

    title: str
    language: str
    canonical_url: str
    extract: str
    page_id: int
    retrieved_at: datetime
    provider_id: str = "wikipedia"
    provider: str = "Wikipedia"
    source_class: str = "ENCYCLOPEDIC"

    @property
    def source_url(self) -> str:
        return self.canonical_url

    @property
    def content(self) -> str:
        return self.extract


def _normalise_query(value: str) -> str:
    return " ".join(value.split()).strip()


def _safe_error(language: str, stage: str, exc: Exception) -> str:
    return f"Wikipedia {language} {stage} failed: {type(exc).__name__}."


def _valid_article_url(value: object, language: str) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    expected_host = f"{language}.wikipedia.org"
    if (
        parts.scheme.casefold() != "https"
        or (parts.hostname or "").casefold() != expected_host
        or parts.username
        or parts.password
        or parts.port not in {None, 443}
        or not parts.path.startswith("/wiki/")
    ):
        return None
    return value


class MediaWikiProvider:
    """Dynamic Wikipedia search with Indonesian-first, English fallback.

    Search snippets are never returned as evidence. A candidate is emitted only
    after a second MediaWiki request returns the actual page extract and its
    provider-supplied canonical URL.
    """

    provider_id = "wikipedia"

    def __init__(
        self,
        *,
        languages: str | list[str] | tuple[str, ...] | None = None,
        timeout: float = 10.0,
        max_results: int = 3,
        cache_ttl_seconds: int = 900,
        transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str | None = None,
    ):
        configured = languages
        if configured is None:
            configured = os.getenv("WIKIPEDIA_LANGS", "id,en")
        raw_languages = (
            configured.split(",") if isinstance(configured, str) else list(configured)
        )
        clean_languages: list[str] = []
        for language in raw_languages:
            code = str(language).strip().casefold()
            if _LANGUAGE_RE.fullmatch(code) and code not in clean_languages:
                clean_languages.append(code)
        self.languages = tuple(clean_languages or ("id", "en"))
        self.timeout = max(0.5, min(float(timeout), 30.0))
        self.max_results = max(1, min(int(max_results), 10))
        self._transport = transport
        self._user_agent = (
            user_agent
            or os.getenv("SANAD_USER_AGENT")
            or "SANAD.AI/0.2 (public-source retrieval)"
        )
        self._cache: _BoundedTTLCache[list[MediaWikiArticle]] = _BoundedTTLCache(
            ttl_seconds=cache_ttl_seconds,
            max_items=128,
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
    ) -> list[MediaWikiArticle]:
        query = _normalise_query(query)
        self.last_errors = []
        self.request_count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        if not query:
            return []

        bounded_limit = max(1, min(int(limit or self.max_results), self.max_results, 10))
        # Language order is meaningful: `id,en` means use English only as a
        # fallback when Indonesian has no retrievable page.
        for language in self.languages:
            articles = await self._search_language(query, language, bounded_limit)
            if articles:
                return articles
        return []

    async def retrieve(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[MediaWikiArticle]:
        return await self.search(query, limit=limit)

    async def _search_language(
        self,
        query: str,
        language: str,
        limit: int,
    ) -> list[MediaWikiArticle]:
        cache_key = f"{language}:{limit}:{query.casefold()}"
        cached, cache_hit = await self._cache.get(cache_key)
        if cache_hit and cached is not None:
            self.cache_hits += 1
            return cached
        self.cache_misses += 1

        endpoint = f"https://{language}.wikipedia.org/w/api.php"
        headers = {
            "Accept": "application/json",
            "User-Agent": self._user_agent,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                transport=self._transport,
                headers=headers,
            ) as client:
                search_response = await client.get(
                    endpoint,
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": query,
                        "srnamespace": 0,
                        "srlimit": limit,
                        "format": "json",
                        "formatversion": 2,
                        "utf8": 1,
                    },
                )
                self.request_count += 1
                search_response.raise_for_status()
                search_payload = search_response.json()
                raw_hits = (
                    search_payload.get("query", {}).get("search", [])
                    if isinstance(search_payload, dict)
                    else []
                )
                page_ids = [
                    str(hit.get("pageid"))
                    for hit in raw_hits
                    if isinstance(hit, dict)
                    and isinstance(hit.get("pageid"), int)
                    and hit["pageid"] > 0
                ][:limit]
                if not page_ids:
                    await self._cache.set(cache_key, [])
                    return []

                page_response = await client.get(
                    endpoint,
                    params={
                        "action": "query",
                        "pageids": "|".join(page_ids),
                        "prop": "extracts|info",
                        "explaintext": 1,
                        "exintro": 1,
                        "inprop": "url",
                        "redirects": 1,
                        "format": "json",
                        "formatversion": 2,
                        "utf8": 1,
                    },
                )
                self.request_count += 1
                page_response.raise_for_status()
                page_payload = page_response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self.last_errors.append(_safe_error(language, "retrieval", exc))
            return []

        raw_pages = (
            page_payload.get("query", {}).get("pages", [])
            if isinstance(page_payload, dict)
            else []
        )
        requested_order = {
            int(page_id): index for index, page_id in enumerate(page_ids)
        }
        ordered_pages = sorted(
            (
                page
                for page in raw_pages
                if isinstance(page, dict) and isinstance(page.get("pageid"), int)
            ),
            key=lambda page: requested_order.get(
                page["pageid"],
                len(requested_order),
            ),
        )[:limit]
        now = datetime.now(timezone.utc)
        articles: list[MediaWikiArticle] = []
        for page in ordered_pages:
            title = str(page.get("title") or "").strip()
            extract = " ".join(str(page.get("extract") or "").split()).strip()
            canonical_url = _valid_article_url(page.get("fullurl"), language)
            if not title or not extract or canonical_url is None:
                continue
            articles.append(
                MediaWikiArticle(
                    title=title,
                    language=language,
                    canonical_url=canonical_url,
                    extract=extract[:12_000],
                    page_id=page["pageid"],
                    retrieved_at=now,
                )
            )

        await self._cache.set(cache_key, articles)
        return articles


# Compatibility-oriented names for callers that use provider/client wording.
WikipediaProvider = MediaWikiProvider
MediaWikiClient = MediaWikiProvider
