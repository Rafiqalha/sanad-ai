import httpx
import pytest

from sanad_core.config import settings
from sanad_core.intent import IntentEngine
from sanad_core.link_validator import DirectLinkValidator
from sanad_core.orchestrator import SanadOrchestrator
from sanad_core.providers.sunnah import SunnahAPIProvider
from sanad_core.query_generator import QueryGenerator
from sanad_core.retrieval import HadithRetrievalPipeline
from sanad_core.schemas import (
    Candidate,
    Domain,
    EvidenceRelation,
    FinalStatus,
    IntentAnalysis,
    LinkState,
    QueryBundle,
    ReconstructedClaim,
)


class SyntheticIntent(IntentEngine):
    def __init__(self):
        self._client = None

    def analyze(self, text):
        return IntentAnalysis(
            original_text=text,
            primary_intent="Synthetic source lookup.",
            explicit_claims=[text],
            domain_candidate=Domain.HADITH,
            ambiguity_score=0.1,
            needs_clarification=False,
        )

    def reconstruct(self, intent):
        return ReconstructedClaim(
            reconstructed_claim="Synthetic fixture body.",
            attribution_target=None,
            search_focus=["synthetic", "fixture", "body"],
            domain=Domain.HADITH,
        )


class SyntheticQueries(QueryGenerator):
    def __init__(self):
        self._client = None

    def generate(self, claim):
        return QueryBundle(indonesian_queries=["synthetic fixture body"])


class SyntheticDiscovery:
    async def search(self, queries):
        return [
            Candidate(
                candidate_id="discovery",
                provider_id="brave",
                provider_name="Brave Search",
                source_type="web_discovery",
                trust_tier=4,
                title="Synthetic fixture body.",
                retrieved_text="Synthetic fixture body.",
                source_url="https://sunnah.com/testcollection:123",
                retrieval_queries=queries,
                metadata_complete=True,
            )
        ]


def _api_transport(number="123"):
    return httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "collection": "testcollection",
                "hadithNumber": number,
                "hadith": [
                    {"lang": "en", "body": "Synthetic fixture body.", "urn": 999}
                ],
            },
        )
    )


def _link_transport():
    return httpx.MockTransport(lambda request: httpx.Response(200))


def _orchestrator(api_number="123"):
    retrieval = HadithRetrievalPipeline(
        discovery=SyntheticDiscovery(),
        hadith_api=None,
        sunnah=SunnahAPIProvider(transport=_api_transport(api_number)),
    )
    return SanadOrchestrator(
        intent_engine=SyntheticIntent(),
        query_generator=SyntheticQueries(),
        retrieval=retrieval,
        link_validator=DirectLinkValidator(transport=_link_transport()),
    )


@pytest.mark.asyncio
async def test_mocked_pipeline_promotes_only_coherent_official_evidence(monkeypatch):
    monkeypatch.setattr(settings, "sunnah_api_key", "private-test-key")
    response = await _orchestrator().search("Synthetic source request.")

    assert response.status == FinalStatus.SUCCESS
    assert response.provider_errors == []
    assert len(response.evidence) == 1
    evidence = response.evidence[0]
    assert evidence.candidate.provider_id == "sunnah"
    assert evidence.link.state == LinkState.VERIFIED_DIRECT
    assert evidence.relationship in {
        EvidenceRelation.DIRECT_MATCH,
        EvidenceRelation.STRONG_RELATED_MATCH,
    }


@pytest.mark.asyncio
async def test_mocked_pipeline_never_promotes_mismatched_api_reference(monkeypatch):
    monkeypatch.setattr(settings, "sunnah_api_key", "private-test-key")
    response = await _orchestrator(api_number="124").search(
        "Synthetic source request."
    )

    assert response.status != FinalStatus.SUCCESS
    assert response.provider_errors
    assert all(item.candidate.provider_id == "brave" for item in response.evidence)
    assert all(
        item.link.state == LinkState.DISCOVERY_ONLY for item in response.evidence
    )
