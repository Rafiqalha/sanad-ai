import httpx
import pytest

from sanad_core.config import settings
from sanad_core.intent import IntentEngine
from sanad_core.link_validator import DirectLinkValidator
from sanad_core.orchestrator import SanadOrchestrator
from sanad_core.providers.hadithapi import HadithAPIProvider
from sanad_core.query_generator import QueryGenerator
from sanad_core.retrieval import HadithRetrievalPipeline
from sanad_core.schemas import Candidate, FinalStatus, LinkState


QUERY = (
    "Katanya kalau orang mencari ilmu dimudahkan jalan menuju surga, "
    "hadisnya dari mana?"
)


def _offline_intent_and_queries():
    intent = IntentEngine()
    intent._client = None
    queries = QueryGenerator()
    queries._client = None
    return intent, queries


def _payload(records):
    return {"status": 200, "hadiths": {"data": records, "total": len(records)}}


def _record(number, english, arabic):
    return {
        "id": number,
        "hadithNumber": str(number),
        "hadithEnglish": english,
        "hadithArabic": arabic,
        "headingEnglish": "Synthetic integration fixture",
        "chapterId": "1",
        "bookSlug": "sahih-muslim",
        "status": "Sahih",
        "book": {"bookName": "Synthetic Book", "bookSlug": "sahih-muslim"},
        "chapter": {"chapterNumber": "1", "chapterEnglish": "Synthetic Chapter"},
    }


class DiscoveryMustNotRun:
    async def search(self, queries):
        raise AssertionError("Brave must not run after a usable HadithAPI result.")


class EmptyDiscovery:
    def __init__(self):
        self.calls = 0

    async def search(self, queries):
        self.calls += 1
        return []


class OneDiscovery:
    def __init__(self):
        self.calls = 0

    async def search(self, queries):
        self.calls += 1
        return [
            Candidate(
                candidate_id="brave-synthetic",
                provider_id="brave",
                provider_name="Brave Search",
                source_type="web_discovery",
                trust_tier=4,
                title="Synthetic discovery candidate",
                retrieved_text="Synthetic discovery candidate about knowledge.",
                source_url="https://sunnah.com/testcollection:123",
                retrieval_queries=queries,
                metadata_complete=True,
            )
        ]


@pytest.mark.asyncio
async def test_full_temporary_provider_path_is_provider_validated_not_direct(
    monkeypatch,
):
    records = [
        _record(
            123,
            "A person follows a path seeking knowledge and a path to paradise is made easy.",
            "شخص يسلك طريقا يطلب فيه العلم إلى الجنة",
        ),
        _record(
            999,
            "A synthetic unrelated fixture about trade.",
            "نص تجريبي عن التجارة",
        ),
    ]
    seen_params = []

    def handler(request: httpx.Request):
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json=_payload(records))

    monkeypatch.setattr(settings, "hadith_api_key", "private-test-key")
    monkeypatch.setattr(settings, "sunnah_api_key", None)
    intent, query_generator = _offline_intent_and_queries()
    retrieval = HadithRetrievalPipeline(
        hadith_api=HadithAPIProvider(transport=httpx.MockTransport(handler)),
        discovery=DiscoveryMustNotRun(),
    )
    orchestrator = SanadOrchestrator(
        intent_engine=intent,
        query_generator=query_generator,
        retrieval=retrieval,
        link_validator=DirectLinkValidator(),
    )

    response = await orchestrator.search(QUERY)

    assert response.status == FinalStatus.SOURCE_FOUND_LINK_UNVERIFIED
    assert response.provider_errors == []
    assert seen_params
    assert any("hadithEnglish" in params for params in seen_params)
    assert any("hadithArabic" in params for params in seen_params)
    assert all("hadithEnglish" not in params or "Katanya" not in params["hadithEnglish"] for params in seen_params)
    assert response.evidence
    assert response.evidence[0].candidate.item_number == "123"
    assert response.evidence[0].ranking.relevance_score > response.evidence[1].ranking.relevance_score
    assert all(item.candidate.provider_id == "hadithapi" for item in response.evidence)
    assert all(item.candidate.provider_api_validated for item in response.evidence)
    assert all(not item.candidate.official_api_validated for item in response.evidence)
    assert all(item.link.state == LinkState.VERIFIED_PROVIDER for item in response.evidence)
    assert all(item.link.state != LinkState.VERIFIED_DIRECT for item in response.evidence)


@pytest.mark.asyncio
async def test_hadithapi_empty_then_brave_empty_returns_insufficient_evidence(
    monkeypatch,
):
    monkeypatch.setattr(settings, "hadith_api_key", "private-test-key")
    monkeypatch.setattr(settings, "sunnah_api_key", None)
    empty_discovery = EmptyDiscovery()
    provider = HadithAPIProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_payload([]))
        )
    )
    intent, query_generator = _offline_intent_and_queries()
    orchestrator = SanadOrchestrator(
        intent_engine=intent,
        query_generator=query_generator,
        retrieval=HadithRetrievalPipeline(
            hadith_api=provider,
            discovery=empty_discovery,
        ),
    )

    response = await orchestrator.search(QUERY)

    assert empty_discovery.calls == 1
    assert response.status == FinalStatus.NO_RELIABLE_SOURCE_FOUND
    assert response.evidence == []
    assert "Belum ditemukan sumber" in response.limited_clarification


@pytest.mark.asyncio
async def test_hadithapi_failure_falls_back_to_discovery_without_secret_leak(
    monkeypatch,
):
    secret = "private-test-key"
    monkeypatch.setattr(settings, "hadith_api_key", secret)
    monkeypatch.setattr(settings, "sunnah_api_key", None)
    discovery = OneDiscovery()
    provider = HadithAPIProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, json={"message": "rate limited"})
        )
    )
    intent, query_generator = _offline_intent_and_queries()
    orchestrator = SanadOrchestrator(
        intent_engine=intent,
        query_generator=query_generator,
        retrieval=HadithRetrievalPipeline(
            hadith_api=provider,
            discovery=discovery,
        ),
    )

    response = await orchestrator.search(QUERY)

    assert discovery.calls == 1
    assert response.provider_errors
    assert secret not in " ".join(response.provider_errors)
    assert all(item.candidate.provider_id == "brave" for item in response.evidence)
    assert all(item.link.state == LinkState.DISCOVERY_ONLY for item in response.evidence)
