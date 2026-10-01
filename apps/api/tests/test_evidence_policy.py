import pytest

from sanad_core.evidence import classify_relation, eligible_for_primary_evidence
from sanad_core.schemas import (
    Candidate,
    EvidenceRelation,
    LinkState,
    LinkValidation,
    RankingFeatures,
)


def _candidate(**changes):
    values = {
        "candidate_id": "synthetic",
        "provider_id": "sunnah",
        "provider_name": "Sunnah.com Official API",
        "source_type": "hadith",
        "trust_tier": 1,
        "collection": "testcollection",
        "item_number": "123",
        "source_url": "https://sunnah.com/testcollection:123",
        "source_identifier": "testcollection:123",
        "metadata_complete": True,
        "official_api_validated": True,
    }
    values.update(changes)
    return Candidate(**values)


def _link(state=LinkState.VERIFIED_DIRECT):
    return LinkValidation(
        state=state,
        original_url="https://sunnah.com/testcollection:123",
        final_url="https://sunnah.com/testcollection:123",
        http_status=200,
        provider_domain_match=True,
    )


def _ranking():
    return RankingFeatures(relevance_score=0.9, semantic_similarity=0.9)


def test_fully_eligible_candidate_can_be_direct_match():
    candidate = _candidate()
    link = _link()
    assert eligible_for_primary_evidence(candidate, link) is True
    assert classify_relation(candidate, _ranking(), link) == EvidenceRelation.DIRECT_MATCH


def test_forged_direct_state_with_wrong_final_item_is_not_eligible():
    candidate = _candidate()
    link = _link()
    link.final_url = "https://sunnah.com/testcollection:999"
    assert eligible_for_primary_evidence(candidate, link) is False
    assert classify_relation(candidate, _ranking(), link) == EvidenceRelation.PARTIAL_MATCH


def test_forged_direct_state_with_mismatched_original_url_is_not_eligible():
    candidate = _candidate()
    link = _link()
    link.original_url = "https://www.sunnah.com/testcollection:123"
    assert eligible_for_primary_evidence(candidate, link) is False


def test_forged_direct_state_with_non_https_final_url_is_not_eligible():
    candidate = _candidate()
    link = _link()
    link.final_url = "http://sunnah.com/testcollection:123"
    assert eligible_for_primary_evidence(candidate, link) is False


@pytest.mark.parametrize(
    "candidate,link",
    [
        (_candidate(trust_tier=4), _link()),
        (_candidate(metadata_complete=False), _link()),
        (_candidate(source_identifier=None), _link()),
        (_candidate(official_api_validated=False), _link()),
        (_candidate(), _link(LinkState.VERIFIED_PROVIDER)),
        (
            _candidate(
                provider_id="brave",
                provider_name="Brave Search",
                trust_tier=4,
            ),
            _link(),
        ),
    ],
)
def test_ineligible_candidate_cannot_be_strong_or_direct(candidate, link):
    relation = classify_relation(candidate, _ranking(), link)
    assert eligible_for_primary_evidence(candidate, link) is False
    assert relation not in {
        EvidenceRelation.DIRECT_MATCH,
        EvidenceRelation.STRONG_RELATED_MATCH,
    }
