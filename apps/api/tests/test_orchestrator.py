import pytest

from sanad_core.orchestrator import SanadOrchestrator
from sanad_core.improvement import ImprovementCategory
from sanad_core.schemas import (
    Candidate,
    Domain,
    FinalStatus,
    IntentAnalysis,
    LinkState,
    LinkValidation,
    QueryBundle,
    RankingFeatures,
    ReconstructedClaim,
)


class FakeIntent:
    def analyze(self, text):
        return IntentAnalysis(
            original_text=text,
            primary_intent="Mencari hadis tentang menuntut ilmu dan jalan menuju surga.",
            explicit_claims=[text],
            inferred_claims=[],
            not_explicitly_asked=["fatwa"],
            entities=[],
            key_concepts=["ilmu", "jalan", "surga"],
            domain_candidate=Domain.HADITH,
            ambiguity_score=0.1,
            needs_clarification=False,
            clarification_question=None,
        )

    def reconstruct(self, intent):
        return ReconstructedClaim(
            reconstructed_claim=(
                "Seseorang yang menempuh jalan untuk mencari ilmu "
                "akan dimudahkan jalannya menuju surga."
            ),
            attribution_target="Prophet Muhammad",
            search_focus=["ilmu", "jalan", "surga"],
            domain=Domain.HADITH,
        )


class FakeQueries:
    def generate(self, claim):
        return QueryBundle(
            indonesian_queries=["hadis mencari ilmu jalan surga"],
            english_queries=["hadith path seeking knowledge paradise"],
            arabic_queries=[],
        )


class FakeRetrieval:
    async def retrieve(self, queries):
        retrieval_queries = (
            queries.all_queries if isinstance(queries, QueryBundle) else queries
        )
        return [
            Candidate(
                candidate_id="1",
                provider_id="sunnah",
                provider_name="Sunnah.com Official API",
                source_type="hadith",
                trust_tier=1,
                title=None,
                collection="testcollection",
                item_number="123",
                language="en",
                retrieved_text="Synthetic fixture body.",
                source_url="https://sunnah.com/testcollection:123",
                source_identifier="testcollection:123",
                retrieval_queries=retrieval_queries,
                metadata_complete=True,
                official_api_validated=True,
            )
        ], []


class FakeReranker:
    def rank(self, claim, candidates):
        return [
            (
                candidates[0],
                RankingFeatures(
                    lexical_overlap=0.8,
                    semantic_similarity=0.92,
                    attribution_match=1.0,
                    metadata_match=1.0,
                    multi_query_agreement=0.66,
                    relevance_score=0.88,
                ),
            )
        ]


class FakeLink:
    async def validate(self, candidate):
        return LinkValidation(
            state=LinkState.VERIFIED_DIRECT,
            original_url=candidate.source_url,
            final_url=candidate.source_url,
            http_status=200,
            provider_domain_match=True,
        )


class WeakDiscoveryRetrieval:
    last_brave_request_count = 2
    last_brave_cache_hits = 0
    last_brave_cache_misses = 2

    async def retrieve(self, queries):
        return [
            Candidate(
                candidate_id="weak-discovery",
                provider_id="brave",
                provider_name="Brave Search (discovery)",
                source_type="web_discovery",
                trust_tier=4,
                title="Unrelated candidate",
                retrieved_text="An unrelated page.",
                source_url="https://sunnah.com/testcollection:999",
                retrieval_queries=queries.all_queries,
                metadata_complete=True,
            )
        ], []


class WeakReranker:
    def rank(self, claim, candidates):
        return [
            (
                candidates[0],
                RankingFeatures(
                    lexical_overlap=0.0,
                    semantic_similarity=0.1,
                    relevance_score=0.1,
                ),
            )
        ]


class DiscoveryOnlyLink:
    async def validate(self, candidate):
        return LinkValidation(
            state=LinkState.DISCOVERY_ONLY,
            original_url=candidate.source_url,
            final_url=candidate.source_url,
            http_status=200,
            provider_domain_match=True,
        )


@pytest.mark.asyncio
async def test_happy_path():
    orch = SanadOrchestrator(
        intent_engine=FakeIntent(),
        query_generator=FakeQueries(),
        retrieval=FakeRetrieval(),
        reranker=FakeReranker(),
        link_validator=FakeLink(),
    )

    response = await orch.search(
        "Katanya kalau mencari ilmu dimudahkan jalan menuju surga?"
    )

    assert response.status == FinalStatus.SUCCESS
    assert response.domain == Domain.HADITH
    assert len(response.evidence) == 1
    assert response.evidence[0].link.state == LinkState.VERIFIED_DIRECT


@pytest.mark.asyncio
async def test_only_insufficient_discovery_candidates_return_no_reliable_source():
    response = await SanadOrchestrator(
        intent_engine=FakeIntent(),
        query_generator=FakeQueries(),
        retrieval=WeakDiscoveryRetrieval(),
        reranker=WeakReranker(),
        link_validator=DiscoveryOnlyLink(),
    ).search("benarkah kutipan rekaan ini adalah hadis?")

    assert response.status == FinalStatus.NO_RELIABLE_SOURCE_FOUND
    assert response.evidence[0].relationship.value == "INSUFFICIENT_EVIDENCE"
    assert response.retrieval_telemetry.structured_candidate_count == 0
    assert response.retrieval_telemetry.web_candidate_count == 1
    assert response.retrieval_telemetry.brave_request_count == 2
    assert response.retrieval_telemetry.brave_request_limit == 2


class AmbiguousIntent(FakeIntent):
    def analyze(self, text):
        x = super().analyze(text)
        x.ambiguity_score = 0.85
        x.needs_clarification = True
        x.clarification_question = "Maksud jalan yang mana?"
        return x


@pytest.mark.asyncio
async def test_ambiguity_stops_retrieval():
    orch = SanadOrchestrator(intent_engine=AmbiguousIntent())
    response = await orch.search("Ada dalil tentang jalan itu?")
    assert response.status == FinalStatus.NEEDS_CLARIFICATION
    assert response.evidence == []


@pytest.mark.asyncio
async def test_orchestrator_tracks_only_sanitized_controlled_improvement_patterns():
    orch = SanadOrchestrator()

    response = await orch.search("cara merawat turbin industri user@example.org")

    assert response.status == FinalStatus.NO_RELIABLE_SOURCE_FOUND
    observations = orch.improvement_tracker.observations()
    categories = {item.category for item in observations}
    assert ImprovementCategory.FAILED_QUERY in categories
    assert ImprovementCategory.NO_RESULT_PATTERN in categories
    assert ImprovementCategory.UNKNOWN_MISROUTE in categories
    assert all("user@example.org" not in item.sanitized_pattern for item in observations)
    assert all("[EMAIL]" in item.sanitized_pattern for item in observations)
