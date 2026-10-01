from pathlib import Path

import pytest

from sanad_core.evidence import (
    build_evidence,
    classify_relation,
    eligible_for_primary_evidence,
)
from sanad_core.link_validator import DirectLinkValidator
from sanad_core.schemas import (
    Candidate,
    EvidenceRelation,
    LinkState,
    LinkValidation,
    RankingFeatures,
)
from sanad_core.source_registry import REGISTRY


def _candidate(**changes):
    values = {
        "candidate_id": "hadithapi-synthetic",
        "provider_id": "hadithapi",
        "provider_name": "HadithAPI",
        "source_type": "hadith_curated_secondary",
        "trust_tier": 2,
        "collection": "sahih-bukhari",
        "item_number": "123",
        "retrieved_text": "Synthetic fixture body about knowledge.",
        "source_url": "https://www.hadithapi.com/public/api/hadiths",
        "source_identifier": "hadithapi:sahih-bukhari:123",
        "metadata_complete": True,
        "provider_api_validated": True,
        "official_api_validated": False,
    }
    values.update(changes)
    return Candidate(**values)


def _ranking(score=0.95):
    return RankingFeatures(
        relevance_score=score,
        semantic_similarity=score,
        lexical_overlap=score,
    )


def test_runtime_and_declarative_registry_keep_hadithapi_secondary():
    registration = REGISTRY["hadithapi"]
    assert registration.trust_tier == 2
    assert registration.evidence_role == "CURATED_SECONDARY"
    assert registration.evidence_role != "PRIMARY_CURATED"

    registry_text = (
        Path(__file__).resolve().parents[1] / "source_registry.yaml"
    ).read_text(encoding="utf-8")
    assert "provider_id: hadithapi" in registry_text
    assert "trust_tier: 2" in registry_text
    assert "evidence_role: CURATED_SECONDARY" in registry_text


@pytest.mark.asyncio
async def test_provider_validated_candidate_is_verified_provider_only():
    result = await DirectLinkValidator().validate(_candidate())

    assert result.state == LinkState.VERIFIED_PROVIDER
    assert result.provider_domain_match is True
    assert result.final_url == "https://www.hadithapi.com/public/api/hadiths"
    assert any("no canonical direct-item URL" in note for note in result.notes)


@pytest.mark.asyncio
async def test_unregistered_hadithapi_path_is_unverified():
    result = await DirectLinkValidator().validate(
        _candidate(source_url="https://www.hadithapi.com/unrelated")
    )

    assert result.state == LinkState.UNVERIFIED


def test_forged_verified_direct_state_never_becomes_primary_or_strong():
    candidate = _candidate()
    link = LinkValidation(
        state=LinkState.VERIFIED_DIRECT,
        original_url=candidate.source_url,
        final_url=candidate.source_url,
        http_status=200,
        provider_domain_match=True,
    )

    assert eligible_for_primary_evidence(candidate, link) is False
    assert classify_relation(candidate, _ranking(), link) == EvidenceRelation.PARTIAL_MATCH


def test_evidence_discloses_secondary_provider_and_missing_direct_item_url():
    candidate = _candidate()
    link = LinkValidation(
        state=LinkState.VERIFIED_PROVIDER,
        original_url=candidate.source_url,
        final_url=candidate.source_url,
        http_status=200,
        provider_domain_match=True,
    )

    evidence = build_evidence(candidate, _ranking(), link)

    assert evidence.relationship == EvidenceRelation.PARTIAL_MATCH
    assert any("curated secondary" in note for note in evidence.limitations)
    assert any("canonical direct-item URL" in note for note in evidence.limitations)
    assert all("Tier-1" not in candidate.source_url for _ in [0])
