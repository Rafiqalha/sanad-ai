from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx

from ..config import settings
from ..schemas import Candidate, SourceClass
from .base import DiscoveryProvider
from .broad_web import AsyncTTLCache
from .sunnah import parse_sunnah_reference


_SUNNAH_HOSTS = {"sunnah.com", "www.sunnah.com", "beta.sunnah.com"}


def classify_sunnah_discovery_url(url: str) -> str:
    """Classify a Brave result without validating its religious/source content."""

    if parse_sunnah_reference(url) is not None:
        return "CANONICAL_ITEM_PATH"

    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or host not in _SUNNAH_HOSTS:
        return "UNAPPROVED_ORIGIN"

    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return "PROVIDER_HOME"
    if segments[0].casefold() == "search":
        return "SEARCH_PAGE"
    if len(segments) <= 2:
        return "COLLECTION_OR_BOOK_PAGE"
    return "NONCANONICAL_ITEM_PATH"


class BraveDiscoveryProvider(DiscoveryProvider):
    provider_id = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(
        self,
        site_domain: str = "sunnah.com",
        transport: httpx.AsyncBaseTransport | None = None,
        cache: AsyncTTLCache[list[Candidate]] | None = None,
    ):
        self.site_domain = site_domain
        self._transport = transport
        self._cache = cache or AsyncTTLCache()
        self.last_filter_counts: dict[str, int] = {}
        self.request_count = 0
        self.cache_hits = 0
        self.cache_misses = 0

    async def search(self, queries: list[str]) -> list[Candidate]:
        if not settings.brave_search_api_key:
            raise RuntimeError("BRAVE_SEARCH_API_KEY is not configured.")

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": settings.brave_search_api_key,
        }
        results: dict[str, Candidate] = {}
        self.request_count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.last_filter_counts = {
            "RAW_RESULTS": 0,
            "CANONICAL_ITEM_PATH": 0,
            "SEARCH_PAGE": 0,
            "PROVIDER_HOME": 0,
            "COLLECTION_OR_BOOK_PAGE": 0,
            "NONCANONICAL_ITEM_PATH": 0,
            "UNAPPROVED_ORIGIN": 0,
        }

        async with httpx.AsyncClient(
            timeout=settings.sanad_http_timeout,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            for query in queries:
                cache_key = (
                    f"{self.site_domain.casefold()}:"
                    f"{' '.join(query.casefold().split())}"
                )
                cached, cache_hit = await self._cache.get(cache_key)
                if cache_hit and cached is not None:
                    self.cache_hits += 1
                    query_candidates = cached
                else:
                    self.cache_misses += 1
                    self.request_count += 1
                    query_candidates = []
                    q = f"site:{self.site_domain} {query}"
                    response = await client.get(
                        self.endpoint,
                        headers=headers,
                        params={
                            "q": q,
                            "count": settings.sanad_max_web_results,
                            "search_lang": "en",
                            "country": "US",
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    for item in (payload.get("web") or {}).get("results", []):
                        self.last_filter_counts["RAW_RESULTS"] += 1
                        url = item.get("url")
                        if not url:
                            continue
                        page_type = classify_sunnah_discovery_url(url)
                        self.last_filter_counts[page_type] += 1
                        if page_type != "CANONICAL_ITEM_PATH":
                            continue
                        cid = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
                        query_candidates.append(
                            Candidate(
                                candidate_id=f"brave-{cid}",
                                provider_id="brave",
                                provider_name="Brave Search (discovery)",
                                source_type="web_discovery",
                                trust_tier=4,
                                title=item.get("title"),
                                retrieved_text=item.get("description"),
                                source_url=url,
                                source_domain=(urlparse(url).hostname or "").casefold(),
                                page_title=item.get("title"),
                                source_class=SourceClass.UNKNOWN,
                                retrieved_at=datetime.now(timezone.utc),
                                retrieval_queries=[query],
                                metadata_complete=bool(item.get("title") and url),
                                raw={**item, "sanad_discovery_page_type": page_type},
                            )
                        )
                    await self._cache.set(cache_key, query_candidates)

                for candidate in query_candidates:
                    url = candidate.source_url
                    existing = results.get(url)
                    if existing:
                        existing.retrieval_queries = list(
                            dict.fromkeys(
                                existing.retrieval_queries
                                + candidate.retrieval_queries
                            )
                        )
                        continue
                    results[url] = candidate
        return list(results.values())
