from scripts.live_smoke_test import smoke_gate_failures
from sanad_core.schemas import (
    Candidate,
    Domain,
    EvidenceItem,
    EvidenceRelation,
    FinalResponse,
    FinalStatus,
    LinkState,
    LinkValidation,
    RankingFeatures,
)


def _result(*, link_state=LinkState.VERIFIED_DIRECT, identifier="testcollection:123"):
    candidate = Candidate(
        candidate_id="synthetic",
        provider_id="sunnah",
        provider_name="Sunnah.com Official API",
        source_type="hadith",
        trust_tier=1,
        collection="testcollection",
        item_number="123",
        retrieved_text="Synthetic fixture body.",
        source_url="https://sunnah.com/testcollection:123",
        source_identifier=identifier,
        metadata_complete=True,
        official_api_validated=True,
    )
    link = LinkValidation(
        state=link_state,
        original_url=candidate.source_url,
        final_url=candidate.source_url,
        http_status=200,
        provider_domain_match=True,
    )
    item = EvidenceItem(
        candidate=candidate,
        ranking=RankingFeatures(relevance_score=0.9, semantic_similarity=0.9),
        link=link,
        relationship=EvidenceRelation.DIRECT_MATCH,
    )
    return FinalResponse(
        understood_intent="Synthetic source lookup.",
        reconstructed_claim="Synthetic claim.",
        domain=Domain.HADITH,
        evidence=[item],
        status=FinalStatus.SUCCESS,
    )


def test_smoke_gate_accepts_coherent_primary_evidence():
    assert smoke_gate_failures(_result()) == []


def test_smoke_gate_rejects_identifier_mismatch():
    failures = smoke_gate_failures(_result(identifier="testcollection:999"))
    assert failures
    assert any("provenance" in failure for failure in failures)


def test_smoke_gate_rejects_non_direct_link():
    failures = smoke_gate_failures(_result(link_state=LinkState.VERIFIED_PROVIDER))
    assert failures
    assert any("No qualified" in failure for failure in failures)
