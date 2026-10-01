from __future__ import annotations

import httpx
import pytest

from sanad_core.config import settings
from sanad_core.evidence import eligible_for_primary_evidence
from sanad_core.intent import IntentEngine
from sanad_core.link_validator import SourceLinkResolver
from sanad_core.orchestrator import SanadOrchestrator
from sanad_core.providers.quran import QuranProvider
from sanad_core.query_generator import QueryGenerator
from sanad_core.retrieval import QuranRetrievalPipeline
from sanad_core.schemas import (
    Candidate,
    Domain,
    FinalStatus,
    LinkState,
    RetrievalMode,
)


class _HadithMustNotRun:
    async def retrieve(self, queries):
        raise AssertionError("HadithAPI/Brave must not run for a QURAN route.")


def _quran_handler(request: httpx.Request):
    if request.url.host == "prelive-oauth2.quran.foundation":
        return httpx.Response(
            200,
            json={"access_token": "fixture-token", "expires_in": 3600},
        )
    if request.url.path == "/content/api/v4/chapters":
        return httpx.Response(
            200,
            json={
                "chapters": [
                    {
                        "id": 2,
                        "name_simple": "Al-Baqarah",
                        "name_arabic": "البقرة",
                        "verses_count": 286,
                    }
                ]
            },
        )
    if request.url.path == "/content/api/v4/resources/translations":
        return httpx.Response(
            200,
            json={
                "translations": [
                    {
                        "id": 7654,
                        "name": "Terjemahan Indonesia Uji",
                        "slug": "id-test",
                        "language_name": "indonesian",
                    }
                ]
            },
        )
    if request.url.path == "/content/api/v4/verses/by_key/2:255":
        assert request.url.params["translations"] == "7654"
        return httpx.Response(
            200,
            json={
                "verse": {
                    "chapter_id": 2,
                    "verse_number": 255,
                    "verse_key": "2:255",
                    "text_uthmani": "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ",
                    "translations": [
                        {
                            "resource_id": 7654,
                            "text": "Terjemahan Indonesia dari provider.",
                        }
                    ],
                }
            },
        )
    if request.url.host in {"quran.com", "www.quran.com"}:
        return httpx.Response(200, text='provider page data-verse-key="2:255"')
    raise AssertionError(f"Unexpected request: {request.url}")


@pytest.mark.asyncio
async def test_quran_exact_end_to_end_with_mocked_official_provider(monkeypatch):
    monkeypatch.setattr(settings, "quran_foundation_client_id", "fixture-client")
    monkeypatch.setattr(settings, "quran_foundation_client_secret", "fixture-secret")
    monkeypatch.setattr(settings, "quran_foundation_env", "prelive")
    transport = httpx.MockTransport(_quran_handler)
    intent = IntentEngine()
    intent._client = None
    queries = QueryGenerator()
    queries._client = None
    orchestrator = SanadOrchestrator(
        intent_engine=intent,
        query_generator=queries,
        retrieval=_HadithMustNotRun(),
        quran_retrieval=QuranRetrievalPipeline(
            provider=QuranProvider(transport=transport)
        ),
        link_validator=SourceLinkResolver(transport=transport),
    )

    response = await orchestrator.search("carikan Al-Baqarah ayat 255")

    assert response.domain == Domain.QURAN
    assert response.status == FinalStatus.SUCCESS
    assert response.retrieval_mode == RetrievalMode.EXACT_REFERENCE
    assert response.response_time_ms is not None
    assert response.response_time_ms >= 0
    assert response.understood_intent.startswith("Menelusuri sumber Al-Qur'an")
    assert response.reconstructed_claim
    assert response.generated_queries
    assert len(response.evidence) == 1
    evidence = response.evidence[0]
    assert evidence.candidate.surah_name == "Al-Baqarah"
    assert evidence.candidate.surah_number == 2
    assert evidence.candidate.verse_number == 255
    assert evidence.candidate.verse_key == "2:255"
    assert evidence.candidate.retrieved_texts["ar"]
    assert evidence.candidate.retrieved_texts["id"]
    assert evidence.candidate.provider_name == "Quran Foundation"
    assert evidence.candidate.canonical_provider_validated is True
    assert evidence.candidate.official_api_validated is False
    assert evidence.link.state == LinkState.VERIFIED_DIRECT
    assert evidence.link.link_state == LinkState.VERIFIED_DIRECT
    assert evidence.link.link_provider == "quran_foundation"
    assert evidence.link.link_validated_at is not None
    assert evidence.link.http_status == 200
    assert eligible_for_primary_evidence(evidence.candidate, evidence.link) is True


@pytest.mark.asyncio
async def test_quran_unavailable_is_honest_and_has_no_candidate_or_url(monkeypatch):
    monkeypatch.setattr(settings, "quran_foundation_client_id", None)
    monkeypatch.setattr(settings, "quran_foundation_client_secret", None)
    intent = IntentEngine()
    intent._client = None
    queries = QueryGenerator()
    queries._client = None
    orchestrator = SanadOrchestrator(
        intent_engine=intent,
        query_generator=queries,
        retrieval=_HadithMustNotRun(),
        quran_retrieval=QuranRetrievalPipeline(provider=QuranProvider()),
    )

    response = await orchestrator.search("carikan Al-Baqarah ayat 255")
    serialized = response.model_dump_json()

    assert response.domain == Domain.QURAN
    assert response.status == FinalStatus.NO_RELIABLE_SOURCE_FOUND
    assert response.limited_clarification == "Sumber Qur’an belum dapat diakses saat ini."
    assert response.retrieval_mode == RetrievalMode.EXACT_REFERENCE
    assert response.evidence == []
    assert "https://quran.com" not in serialized


@pytest.mark.asyncio
async def test_quran_direct_link_mismatch_cannot_be_verified_direct():
    candidate = Candidate(
        candidate_id="quran-test",
        provider_id="quran_foundation",
        provider_name="Quran Foundation",
        source_type="quran_canonical",
        trust_tier=1,
        source_url="https://quran.com/2/255",
        source_identifier="quran:2:255",
        metadata_complete=True,
        provider_api_validated=True,
        canonical_provider_validated=True,
        verse_key="2:255",
        surah_name="Al-Baqarah",
        surah_number=2,
        verse_number=255,
    )

    def redirect_to_other_verse(request: httpx.Request):
        if request.url.path == "/2/255":
            return httpx.Response(302, headers={"Location": "https://quran.com/2/256"})
        return httpx.Response(200)

    result = await SourceLinkResolver(
        transport=httpx.MockTransport(redirect_to_other_verse)
    ).validate(candidate)

    assert result.state == LinkState.VERIFIED_PROVIDER
    assert eligible_for_primary_evidence(candidate, result) is False
