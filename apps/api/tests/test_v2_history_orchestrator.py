from datetime import datetime, timezone

import pytest

from sanad_core.history_pipeline import HistoryRetrievalResult, ProvenanceSource
from sanad_core.orchestrator import SanadOrchestrator
from sanad_core.schemas import Domain, FinalStatus, LinkState, SourceClass


class _MockHistoryPipeline:
    async def retrieve(self, query, *, generated_queries, max_results=12):
        now = datetime.now(timezone.utc)
        wiki = ProvenanceSource(
            title="Pertempuran Badar",
            provider_ids=("wikipedia",),
            provider="Wikipedia",
            source_class="ENCYCLOPEDIC",
            source_url="https://id.wikipedia.org/wiki/Pertempuran_Badar",
            resolved_url="https://id.wikipedia.org/wiki/Pertempuran_Badar",
            link_state="VERIFIED_PROVIDER",
            validation_timestamp=now,
            summary="Ringkasan ensiklopedis dari halaman aktual.",
            content="Ringkasan ensiklopedis dari halaman aktual.",
            language="id",
            relevance_score=0.9,
            retrieval_queries=(query,),
        )
        fetched = ProvenanceSource(
            title="Koleksi manuskrip tentang Badar",
            provider_ids=("brave_web_discovery",),
            provider="Brave Search + fetched page",
            source_class="INSTITUTIONAL",
            source_url="https://library.example.edu/badr",
            resolved_url="https://library.example.edu/badr",
            link_state="DISCOVERY_ONLY",
            validation_timestamp=now,
            content="Halaman perpustakaan yang diambil dan relevan.",
            institution="Example University Library",
            relevance_score=0.7,
            retrieval_queries=(query,),
            metadata={"http_status": 200},
        )
        return HistoryRetrievalResult(
            query=query,
            generated_queries=(query, generated_queries[0]),
            sources=(wiki, fetched),
            encyclopedic_sources=(wiki,),
            academic_sources=(),
            institutional_sources=(),
            broad_web_sources=(fetched,),
            errors=(),
            provider_counts={
                "wikipedia": 1,
                "openalex": 0,
                "crossref": 0,
                "broad_web": 1,
            },
            provider_telemetry={
                "wikipedia_requests": 2,
                "wikipedia_cache_misses": 1,
                "brave_requests": 1,
                "brave_cache_misses": 1,
                "web_candidate_count": 2,
                "fetched_page_count": 1,
                "page_cache_misses": 1,
            },
            retrieved_at=now,
        )


@pytest.mark.asyncio
async def test_history_route_keeps_provider_and_discovery_boundaries_separate():
    response = await SanadOrchestrator(
        history_retrieval=_MockHistoryPipeline(),
    ).search("bagaimana sejarah Perang Badar?")

    assert response.status == FinalStatus.SUCCESS
    assert response.domain == Domain.ISLAMIC_HISTORY
    assert response.evidence == []
    assert len(response.web_results) == 2
    wiki, fetched = response.web_results
    assert wiki.source_class == SourceClass.ENCYCLOPEDIC
    assert wiki.link_state == LinkState.VERIFIED_PROVIDER
    assert wiki.link_validated_at is None
    assert fetched.link_state == LinkState.DISCOVERY_ONLY
    assert fetched.link_validated_at is not None
    assert fetched.http_status == 200
    assert response.retrieval_telemetry.brave_request_count == 1
    assert response.retrieval_telemetry.brave_request_limit == 2
    assert response.retrieval_telemetry.web_candidate_count == 2
    assert response.generated_structured_queries[0] == (
        "bagaimana sejarah Perang Badar?"
    )

