from __future__ import annotations

import asyncio

from rapidfuzz.fuzz import token_set_ratio

from .config import settings
from .providers.broad_web import (
    BroadWebDiscoveryProvider,
    WebPageRetriever,
    WebSearchHit,
)
from .schemas import (
    CacheState,
    QueryBundle,
    ReconstructedClaim,
    RetrievalTelemetry,
    WebSourceResult,
)


class WebDiscoveryPipeline:
    """Independent discovery/provenance path; it never verifies evidence."""

    def __init__(
        self,
        provider: BroadWebDiscoveryProvider | None = None,
        page_retriever: WebPageRetriever | None = None,
    ):
        self.provider = provider or BroadWebDiscoveryProvider()
        self.page_retriever = page_retriever or WebPageRetriever()

    async def retrieve(
        self,
        claim: ReconstructedClaim,
        queries: QueryBundle,
    ) -> tuple[list[WebSourceResult], list[str], RetrievalTelemetry]:
        telemetry = RetrievalTelemetry(
            brave_request_limit=settings.sanad_max_brave_requests,
        )
        if not settings.sanad_enable_broad_web_discovery or not queries.web_queries:
            return [], [], telemetry

        batch = await self.provider.search(
            queries.web_queries,
            max_requests=settings.sanad_max_brave_requests,
        )
        telemetry.web_candidate_count = len(batch.hits)
        telemetry.brave_request_count = batch.brave_request_count
        telemetry.search_cache_hits = batch.cache_hits
        telemetry.search_cache_misses = batch.cache_misses

        ranked_hits = sorted(
            batch.hits,
            key=lambda hit: self._hit_score(hit, claim.reconstructed_claim),
            reverse=True,
        )[: settings.sanad_max_web_pages]

        outcomes = await asyncio.gather(
            *(
                self.page_retriever.fetch(
                    hit,
                    relevance_queries=queries.web_queries
                    + [claim.reconstructed_claim],
                )
                for hit in ranked_hits
            )
        )
        results: list[WebSourceResult] = []
        errors = list(batch.errors)
        for outcome in outcomes:
            if outcome.cache_hit:
                telemetry.page_cache_hits += 1
            else:
                telemetry.page_cache_misses += 1
            if outcome.result is not None:
                results.append(outcome.result)
            elif outcome.error:
                errors.append(outcome.error)
        telemetry.fetched_page_count = len(results)

        total_hits = telemetry.search_cache_hits + telemetry.page_cache_hits
        total_misses = telemetry.search_cache_misses + telemetry.page_cache_misses
        if total_hits and total_misses:
            telemetry.cache_state = CacheState.PARTIAL
        elif total_hits:
            telemetry.cache_state = CacheState.HIT
        elif total_misses:
            telemetry.cache_state = CacheState.MISS
        results.sort(key=lambda item: item.relevance_score, reverse=True)
        return results, list(dict.fromkeys(errors)), telemetry

    @staticmethod
    def _hit_score(hit: WebSearchHit, claim: str) -> float:
        text = f"{hit.page_title} {hit.snippet or ''}"
        lexical = token_set_ratio(claim.casefold(), text.casefold()) / 100.0
        return lexical + (1 / max(1, hit.rank)) * 0.05

