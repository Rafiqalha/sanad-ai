from __future__ import annotations

import asyncio
from copy import deepcopy
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import re
import socket
import time
from typing import Any, Generic, TypeVar
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from rapidfuzz.fuzz import token_set_ratio

from ..config import settings
from ..schemas import LinkState, SourceClass, WebSourceResult
from ..semantic_router import normalized_concepts


_T = TypeVar("_T")
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_IGNORED_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "form", "aside"}
_MEANINGLESS = {
    "ada", "aku", "apa", "apakah", "atau", "bahwa", "carikan", "cari",
    "dalam", "dan", "dari", "di", "itu", "katanya", "mengenai", "sumber",
    "tentang", "the", "a", "an", "of", "about", "source", "web", "yang",
}


class AsyncTTLCache(Generic[_T]):
    """Small process-local cache for paid search and repeated page fetches."""

    def __init__(self, ttl_seconds: int | None = None, max_items: int = 256):
        self.ttl_seconds = ttl_seconds or settings.sanad_web_cache_ttl_seconds
        self.max_items = max_items
        self._items: OrderedDict[str, tuple[float, _T]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> tuple[_T | None, bool]:
        async with self._lock:
            item = self._items.get(key)
            if not item:
                return None, False
            expires_at, value = item
            if expires_at <= time.monotonic():
                self._items.pop(key, None)
                return None, False
            self._items.move_to_end(key)
            return deepcopy(value), True

    async def set(self, key: str, value: _T) -> None:
        async with self._lock:
            self._items[key] = (
                time.monotonic() + self.ttl_seconds,
                deepcopy(value),
            )
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)


@dataclass
class WebSearchHit:
    source_url: str
    page_title: str
    snippet: str | None
    retrieval_queries: list[str] = field(default_factory=list)
    rank: int = 0


@dataclass
class WebSearchBatch:
    hits: list[WebSearchHit] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    brave_request_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


@dataclass
class PageFetchOutcome:
    result: WebSourceResult | None
    error: str | None = None
    cache_hit: bool = False


def _cache_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _safe_error(prefix: str, exc: Exception) -> str:
    return f"{prefix}: {type(exc).__name__}."


class BroadWebDiscoveryProvider:
    """Unrestricted Brave discovery; results are never verified evidence."""

    endpoint = "https://api.search.brave.com/res/v1/web/search"
    provider_id = "brave_web_discovery"

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: AsyncTTLCache[list[WebSearchHit]] | None = None,
    ):
        self._transport = transport
        self._cache = cache or AsyncTTLCache()

    @property
    def configured(self) -> bool:
        return bool(settings.brave_search_api_key)

    async def search(
        self,
        queries: list[str],
        *,
        max_requests: int | None = None,
    ) -> WebSearchBatch:
        limit = min(
            3,
            max_requests or settings.sanad_max_brave_requests,
            settings.sanad_max_brave_requests,
        )
        unique_queries: list[str] = []
        seen: set[str] = set()
        for query in queries:
            query = " ".join(query.split()).strip()
            key = _cache_key(query)
            if query and key not in seen:
                seen.add(key)
                unique_queries.append(query)
            if len(unique_queries) >= limit:
                break

        batch = WebSearchBatch()
        if not unique_queries:
            return batch
        if not self.configured:
            batch.errors.append("Brave Search credentials are not configured.")
            return batch

        async def retrieve(query: str) -> tuple[list[WebSearchHit], bool, str | None]:
            key = _cache_key(query)
            cached, hit = await self._cache.get(key)
            if hit and cached is not None:
                return cached, True, None

            try:
                async with httpx.AsyncClient(
                    timeout=settings.sanad_http_timeout,
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    response = await client.get(
                        self.endpoint,
                        headers={
                            "Accept": "application/json",
                            "X-Subscription-Token": settings.brave_search_api_key or "",
                        },
                        params={
                            "q": query,
                            "count": min(settings.sanad_max_web_results, 10),
                            "safesearch": "moderate",
                        },
                    )
                if response.status_code != 200:
                    return [], False, (
                        "Brave broad discovery returned HTTP "
                        f"{response.status_code}."
                    )
                payload = response.json()
                raw_results = (
                    payload.get("web", {}).get("results", [])
                    if isinstance(payload, dict)
                    else []
                )
                parsed: list[WebSearchHit] = []
                for index, item in enumerate(raw_results, start=1):
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    title = str(item.get("title") or "").strip()
                    if not url or not title:
                        continue
                    parsed.append(
                        WebSearchHit(
                            source_url=url,
                            page_title=title,
                            snippet=(str(item.get("description") or "").strip() or None),
                            retrieval_queries=[query],
                            rank=index,
                        )
                    )
                await self._cache.set(key, parsed)
                return parsed, False, None
            except (httpx.RequestError, ValueError) as exc:
                return [], False, _safe_error("Brave broad discovery failed", exc)

        results = await asyncio.gather(*(retrieve(query) for query in unique_queries))
        merged: dict[str, WebSearchHit] = {}
        for items, cache_hit, error in results:
            if cache_hit:
                batch.cache_hits += 1
            else:
                batch.cache_misses += 1
                batch.brave_request_count += 1
            if error:
                batch.errors.append(error)
            for item in items:
                key = item.source_url.rstrip("/")
                existing = merged.get(key)
                if existing:
                    existing.retrieval_queries = list(
                        dict.fromkeys(existing.retrieval_queries + item.retrieval_queries)
                    )
                    existing.rank = min(existing.rank, item.rank)
                else:
                    merged[key] = item
        batch.hits = list(merged.values())
        return batch


class _ReadableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []
        self.main_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self._stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        self._stack.append(tag)
        if tag != "meta":
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        name = (values.get("name") or values.get("property") or "").casefold()
        content = values.get("content", "").strip()
        if name and content:
            self.meta.setdefault(name, content)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "meta":
            values = {key.casefold(): value or "" for key, value in attrs}
            name = (values.get("name") or values.get("property") or "").casefold()
            content = values.get("content", "").strip()
            if name and content:
                self.meta.setdefault(name, content)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split()).strip()
        if not value or any(tag in _IGNORED_TAGS for tag in self._stack):
            return
        if "title" in self._stack:
            self.title_parts.append(value)
        if "body" in self._stack:
            self.body_parts.append(value)
        if "article" in self._stack or "main" in self._stack:
            self.main_parts.append(value)


def classify_source(domain: str, metadata: dict[str, str]) -> SourceClass:
    """Classify provenance only; this intentionally does not judge truth."""

    domain = domain.casefold().removeprefix("www.")
    if (
        domain.endswith(".go.id")
        or domain.endswith(".gov")
        or domain.endswith(".gov.id")
        or domain == "kemenag.go.id"
    ):
        return SourceClass.OFFICIAL_GOVERNMENT
    if domain in {"quran.com", "sunnah.com"} or domain.endswith(".quran.com"):
        return SourceClass.PRIMARY_RELIGIOUS_SOURCE
    if (
        domain.endswith(".wikipedia.org")
        or domain.endswith(".wikimedia.org")
        or domain == "wikipedia.org"
    ):
        return SourceClass.ENCYCLOPEDIC
    if (
        "citation_title" in metadata
        or "citation_journal_title" in metadata
        or "citation_doi" in metadata
        or (
            (domain.endswith(".edu") or domain.endswith(".ac.id"))
            and any(
                marker in domain.split(".")
                for marker in ("journal", "journals", "ejournal", "repository")
            )
        )
    ):
        return SourceClass.ACADEMIC
    if domain.endswith(".edu") or domain.endswith(".ac.id"):
        # A university domain establishes institutional provenance, not that
        # every page on it is a peer-reviewed academic work.
        return SourceClass.INSTITUTIONAL
    community_markers = (
        "reddit.com", "quora.com", "facebook.com", "x.com", "twitter.com",
        "instagram.com", "tiktok.com", "stackexchange.com",
    )
    if any(domain == marker or domain.endswith(f".{marker}") for marker in community_markers):
        return SourceClass.COMMUNITY
    if any(
        metadata.get(key)
        for key in ("article:publisher", "publisher", "og:site_name")
    ):
        return SourceClass.PUBLISHER
    if domain.endswith(".org") or domain.endswith(".or.id"):
        return SourceClass.INSTITUTIONAL
    return SourceClass.GENERAL_WEB if domain else SourceClass.UNKNOWN


def _relevance_score(queries: list[str], title: str, text: str) -> float:
    haystack = " ".join(normalized_concepts(f"{title} {text[:12000]}"))
    hay_tokens = set(haystack.split())
    best = 0.0
    for query in queries:
        query_tokens = [
            token for token in normalized_concepts(query)
            if len(token) > 2 and token not in _MEANINGLESS
        ]
        if not query_tokens:
            continue
        overlap = len(set(query_tokens) & hay_tokens) / len(set(query_tokens))
        fuzzy = token_set_ratio(" ".join(query_tokens), haystack[:5000]) / 100.0
        best = max(best, (0.72 * overlap) + (0.28 * fuzzy))
    return round(min(1.0, best), 4)


def _canonicalize_url(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme.casefold(), parts.netloc, parts.path or "/", parts.query, ""))


async def _assert_public_url(value: str, *, skip_dns: bool = False) -> None:
    parts = urlsplit(value)
    if parts.scheme.casefold() != "https":
        raise ValueError("only HTTPS web sources are allowed")
    if not parts.hostname or parts.username or parts.password:
        raise ValueError("invalid public URL")
    expected_port = 443
    if parts.port not in {None, expected_port}:
        raise ValueError("non-standard URL port")
    hostname = parts.hostname.casefold().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise ValueError("local URL is not allowed")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal and not literal.is_global:
        raise ValueError("non-public URL is not allowed")
    if skip_dns or literal:
        return
    records = await asyncio.to_thread(
        socket.getaddrinfo,
        hostname,
        expected_port,
        type=socket.SOCK_STREAM,
    )
    addresses = {record[4][0] for record in records}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("URL does not resolve exclusively to public addresses")


class WebPageRetriever:
    """Fetch, resolve, extract and semantically validate web candidates."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: AsyncTTLCache[WebSourceResult] | None = None,
    ):
        self._transport = transport
        self._cache = cache or AsyncTTLCache()

    async def fetch(
        self,
        hit: WebSearchHit,
        *,
        relevance_queries: list[str],
    ) -> PageFetchOutcome:
        key = _cache_key(hit.source_url)
        cached, cache_hit = await self._cache.get(key)
        if cache_hit and cached is not None:
            # The page body may be reused, but relevance is query-specific.
            # Re-score every cache hit so a page accepted for query A cannot
            # silently become evidence for an unrelated query B.
            rescored = _relevance_score(
                relevance_queries,
                cached.page_title,
                cached.content_excerpt or "",
            )
            if rescored < 0.20:
                return PageFetchOutcome(
                    None,
                    "Cached web page content was not relevant to the query.",
                    cache_hit=True,
                )
            cached = cached.model_copy(deep=True)
            cached.relevance_score = rescored
            cached.retrieval_queries = list(
                dict.fromkeys(cached.retrieval_queries + hit.retrieval_queries)
            )
            return PageFetchOutcome(cached, cache_hit=True)

        try:
            current = _canonicalize_url(hit.source_url)
            for _ in range(6):
                await _assert_public_url(current, skip_dns=self._transport is not None)
                async with httpx.AsyncClient(
                    timeout=settings.sanad_http_timeout,
                    follow_redirects=False,
                    transport=self._transport,
                    headers={
                        "User-Agent": "SANAD.AI-ProvenanceBot/0.1 (+source-validation)",
                        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
                    },
                ) as client:
                    async with client.stream("GET", current) as response:
                        if response.status_code in _REDIRECT_CODES:
                            location = response.headers.get("location")
                            if not location:
                                return PageFetchOutcome(None, "Web page redirect omitted Location.")
                            current = _canonicalize_url(urljoin(current, location))
                            continue
                        if response.status_code != 200:
                            return PageFetchOutcome(
                                None,
                                f"Web page returned HTTP {response.status_code}.",
                            )
                        content_type = response.headers.get("content-type", "").casefold()
                        if not any(kind in content_type for kind in ("text/html", "application/xhtml+xml", "text/plain")):
                            return PageFetchOutcome(None, "Web page was not readable HTML/text.")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > settings.sanad_web_max_content_bytes:
                                return PageFetchOutcome(None, "Web page exceeded the safe content limit.")
                        encoding = response.encoding or "utf-8"
                        html = bytes(body).decode(encoding, errors="replace")
                        http_status = response.status_code
                        final_headers = dict(response.headers)
                        break
            else:
                return PageFetchOutcome(None, "Web page exceeded the redirect limit.")

            parser = _ReadableHTMLParser()
            parser.feed(html)
            readable_parts = parser.main_parts or parser.body_parts
            readable = " ".join(readable_parts)
            readable = re.sub(r"\s+", " ", readable).strip()
            if len(readable) < 80:
                return PageFetchOutcome(None, "Web page did not expose enough readable content.")
            page_title = (
                parser.meta.get("og:title")
                or " ".join(parser.title_parts).strip()
                or hit.page_title
            )
            score = _relevance_score(relevance_queries, page_title, readable)
            if score < 0.20:
                return PageFetchOutcome(None, "Web page content was not relevant to the query.")

            final_url = _canonicalize_url(current)
            domain = (urlsplit(final_url).hostname or "").casefold().removeprefix("www.")
            metadata = parser.meta
            publisher = (
                metadata.get("article:publisher")
                or metadata.get("publisher")
                or metadata.get("og:site_name")
            )
            author = metadata.get("author") or metadata.get("article:author")
            publication_date = (
                metadata.get("article:published_time")
                or metadata.get("date")
                or metadata.get("datepublished")
                or final_headers.get("last-modified")
            )
            now = datetime.now(timezone.utc)
            result = WebSourceResult(
                source_url=hit.source_url,
                resolved_url=final_url,
                source_domain=domain,
                page_title=page_title,
                source_class=classify_source(domain, metadata),
                publisher=publisher,
                institution=publisher,
                author=author,
                publication_date=publication_date,
                snippet=hit.snippet,
                content_excerpt=readable[:900],
                relevance_score=score,
                evidence_state=LinkState.DISCOVERY_ONLY,
                link_state=LinkState.DISCOVERY_ONLY,
                link_provider=BroadWebDiscoveryProvider.provider_id,
                retrieved_at=now,
                link_validated_at=now,
                http_status=http_status,
                retrieval_queries=list(dict.fromkeys(hit.retrieval_queries)),
            )
            await self._cache.set(key, result)
            return PageFetchOutcome(result)
        except (httpx.RequestError, ValueError, UnicodeError, socket.gaierror) as exc:
            return PageFetchOutcome(None, _safe_error("Web page validation failed", exc))
