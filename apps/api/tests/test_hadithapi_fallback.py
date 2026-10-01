import pytest

from sanad_core.config import settings
from sanad_core.providers.hadithapi import HadithAPIError
from sanad_core.retrieval import HadithRetrievalPipeline
from sanad_core.schemas import Candidate, QueryBundle


def _curated_candidate():
    return Candidate(
        candidate_id="hadithapi-synthetic",
        provider_id="hadithapi",
        provider_name="HadithAPI",
        source_type="hadith_curated_secondary",
        trust_tier=2,
        collection="sahih-bukhari",
        item_number="123",
        retrieved_text="Synthetic knowledge fixture.",
        retrieved_texts={"en": "Synthetic knowledge fixture."},
        source_url="https://www.hadithapi.com/public/api/hadiths",
        source_identifier="hadithapi:sahih-bukhari:123",
        metadata_complete=True,
        provider_api_validated=True,
        official_api_validated=False,
    )


def _discovery_candidate():
    return Candidate(
        candidate_id="brave-synthetic",
        provider_id="brave",
        provider_name="Brave Search",
        source_type="web_discovery",
        trust_tier=4,
        title="Synthetic discovery result",
        source_url="https://sunnah.com/testcollection:123",
        metadata_complete=True,
        official_api_validated=False,
    )


class RecordingHadithAPI:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else []
        self.error = error
        self.requests = []

    async def search(self, request, retrieval_queries=None):
        self.requests.append((request, retrieval_queries))
        if self.error:
            raise self.error
        return [item.model_copy(deep=True) for item in self.result]


class RecordingDiscovery:
    def __init__(self, result=None):
        self.result = result if result is not None else []
        self.calls = []

    async def search(self, queries):
        self.calls.append(queries)
        return [item.model_copy(deep=True) for item in self.result]


def _bundle():
    return QueryBundle(
        indonesian_queries=["hadis mencari ilmu jalan surga"],
        english_queries=["hadith seeking knowledge path paradise"],
        arabic_queries=["حديث طلب العلم طريق الجنة"],
        concept_queries=["hadis ilmu jalan surga"],
    )


@pytest.mark.asyncio
async def test_hadithapi_success_prevents_brave_call(monkeypatch):
    monkeypatch.setattr(settings, "sunnah_api_key", None)
    hadith_api = RecordingHadithAPI([_curated_candidate()])
    discovery = RecordingDiscovery([_discovery_candidate()])
    pipeline = HadithRetrievalPipeline(
        hadith_api=hadith_api,
        discovery=discovery,
    )

    candidates, errors = await pipeline.retrieve(_bundle())

    assert errors == []
    assert len(candidates) == 1
    assert candidates[0].provider_id == "hadithapi"
    assert discovery.calls == []
    assert len(hadith_api.requests) == 2
    sent_requests = [request for request, _ in hadith_api.requests]
    assert {bool(request.hadith_english) for request in sent_requests} == {False, True}
    assert {bool(request.hadith_arabic) for request in sent_requests} == {False, True}
    assert all(
        "hadis mencari ilmu" not in " ".join(request.semantic_queries).casefold()
        for request in sent_requests
    )


@pytest.mark.asyncio
async def test_empty_hadithapi_result_calls_brave_once(monkeypatch):
    monkeypatch.setattr(settings, "sunnah_api_key", None)
    hadith_api = RecordingHadithAPI([])
    discovery = RecordingDiscovery([_discovery_candidate()])
    pipeline = HadithRetrievalPipeline(hadith_api=hadith_api, discovery=discovery)

    candidates, errors = await pipeline.retrieve(_bundle())

    assert errors == []
    assert len(discovery.calls) == 1
    assert candidates[0].provider_id == "brave"
    assert candidates[0].official_api_validated is False


@pytest.mark.asyncio
async def test_hadithapi_failure_is_recorded_and_brave_fallback_continues(monkeypatch):
    monkeypatch.setattr(settings, "sunnah_api_key", None)
    hadith_api = RecordingHadithAPI(error=HadithAPIError("HTTP 429"))
    discovery = RecordingDiscovery([_discovery_candidate()])
    pipeline = HadithRetrievalPipeline(hadith_api=hadith_api, discovery=discovery)

    candidates, errors = await pipeline.retrieve(_bundle())

    assert candidates[0].provider_id == "brave"
    assert len(discovery.calls) == 1
    assert len(errors) == 2
    assert all("HadithAPI" in error and "HTTP 429" in error for error in errors)


@pytest.mark.asyncio
async def test_both_providers_empty_returns_no_candidates(monkeypatch):
    monkeypatch.setattr(settings, "sunnah_api_key", None)
    pipeline = HadithRetrievalPipeline(
        hadith_api=RecordingHadithAPI([]),
        discovery=RecordingDiscovery([]),
    )

    candidates, errors = await pipeline.retrieve(_bundle())

    assert candidates == []
    assert errors == []


@pytest.mark.asyncio
async def test_language_incomplete_bundle_skips_hadithapi_and_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "sunnah_api_key", None)
    hadith_api = RecordingHadithAPI([_curated_candidate()])
    discovery = RecordingDiscovery([])
    bundle = QueryBundle(
        indonesian_queries=["hadis mencari ilmu"],
        english_queries=["hadith seeking knowledge"],
        arabic_queries=[],
    )
    pipeline = HadithRetrievalPipeline(hadith_api=hadith_api, discovery=discovery)

    candidates, errors = await pipeline.retrieve(bundle)

    assert candidates == []
    assert hadith_api.requests == []
    assert len(discovery.calls) == 1
    assert any("English and Arabic" in error for error in errors)


@pytest.mark.asyncio
async def test_duplicate_english_arabic_hits_merge_retrieval_queries(monkeypatch):
    monkeypatch.setattr(settings, "sunnah_api_key", None)
    hadith_api = RecordingHadithAPI([_curated_candidate()])
    discovery = RecordingDiscovery([])
    pipeline = HadithRetrievalPipeline(hadith_api=hadith_api, discovery=discovery)

    candidates, errors = await pipeline.retrieve(_bundle())

    assert errors == []
    assert len(candidates) == 1
    assert candidates[0].retrieval_queries == [
        "hadith seeking knowledge path paradise",
        "حديث طلب العلم طريق الجنة",
    ]
