from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from sanad_core.config import settings
from sanad_core.intent import IntentEngine
from sanad_core.providers.quran import (
    QuranProvider,
    QuranProviderError,
    QuranProviderUnavailable,
)
from sanad_core.query_generator import QueryGenerator
from sanad_core.schemas import RetrievalMode


CHAPTERS = [
    {
        "id": 2,
        "name_simple": "Al-Baqarah",
        "name_arabic": "البقرة",
        "verses_count": 286,
    },
    {
        "id": 16,
        "name_simple": "An-Nahl",
        "name_arabic": "النحل",
        "verses_count": 128,
    },
    {
        "id": 24,
        "name_simple": "An-Nur",
        "name_arabic": "النور",
        "verses_count": 64,
    },
    {
        "id": 31,
        "name_simple": "Luqman",
        "name_arabic": "لقمان",
        "verses_count": 34,
    },
    {
        "id": 112,
        "name_simple": "Al-Ikhlas",
        "name_arabic": "الإخلاص",
        "verses_count": 4,
    },
]


def _translation_payload():
    # The selected Indonesian ID is intentionally unusual to prove it comes
    # from provider metadata rather than a production constant.
    return {
        "translations": [
            {
                "id": 41,
                "name": "English fixture",
                "slug": "english-fixture",
                "language_name": "english",
            },
            {
                "id": 9876,
                "name": "Terjemahan Indonesia Fixture",
                "slug": "id-fixture",
                "language_name": "indonesian",
            },
        ]
    }


def _verse_payload(key: str):
    chapter, verse = [int(value) for value in key.split(":")]
    return {
        "verse": {
            "chapter_id": chapter,
            "verse_number": verse,
            "verse_key": key,
            "text_uthmani": f"نص عربي تجريبي {key}",
            "translations": [
                {
                    "resource_id": 9876,
                    "resource_name": "Terjemahan Indonesia Fixture",
                    "language_name": "indonesian",
                    "text": f"Terjemahan Indonesia untuk {key}<sup>1</sup>",
                }
            ],
        }
    }


def _query_bundle(text: str):
    engine = IntentEngine()
    engine._client = None
    generator = QueryGenerator()
    generator._client = None
    claim = engine.reconstruct(engine.analyze(text))
    return claim, generator.generate(claim)


@pytest.fixture(autouse=True)
def configured_quran(monkeypatch):
    monkeypatch.setattr(settings, "quran_foundation_client_id", "fixture-client")
    monkeypatch.setattr(settings, "quran_foundation_client_secret", "fixture-secret")
    monkeypatch.setattr(settings, "quran_foundation_env", "prelive")
    monkeypatch.setattr(settings, "sanad_quran_max_results", 5)


@pytest.mark.asyncio
async def test_exact_named_reference_uses_chapters_then_content_without_search():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path == "/oauth2/token":
            assert b"scope=content" in request.content
            return httpx.Response(
                200,
                json={"access_token": "content-token", "expires_in": 3600},
            )
        assert request.headers["x-client-id"] == "fixture-client"
        assert request.headers["x-auth-token"] == "content-token"
        if request.url.path == "/content/api/v4/chapters":
            return httpx.Response(200, json={"chapters": CHAPTERS})
        if request.url.path == "/content/api/v4/resources/translations":
            return httpx.Response(200, json=_translation_payload())
        if request.url.path == "/content/api/v4/verses/by_key/2:255":
            assert request.url.params["translations"] == "9876"
            return httpx.Response(200, json=_verse_payload("2:255"))
        raise AssertionError(f"Unexpected request: {request.url}")

    provider = QuranProvider(transport=httpx.MockTransport(handler))
    claim, queries = _query_bundle("carikan Al-Baqarah ayat 255")
    result = await provider.retrieve(claim.source_text or "", queries)

    assert result.mode == RetrievalMode.EXACT_REFERENCE
    assert result.errors == []
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.verse_key == "2:255"
    assert candidate.surah_name == "Al-Baqarah"
    assert candidate.surah_number == 2
    assert candidate.verse_number == 255
    assert candidate.retrieved_texts["ar"].startswith("نص عربي")
    assert candidate.retrieved_texts["id"] == "Terjemahan Indonesia untuk 2:255 1"
    assert candidate.translation_name == "Terjemahan Indonesia Fixture"
    assert candidate.canonical_provider_validated is True
    assert candidate.official_api_validated is False
    assert candidate.source_url == "https://quran.com/2/255"
    assert not any(request.url.path.startswith("/search/") for request in requests)
    assert sum(request.url.path == "/oauth2/token" for request in requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unseen_query,provider_key",
    [
        ("ayat mengenai larangan mengolok-olok kelompok lain", "24:11"),
        ("ayat tentang lebah yang mengeluarkan sesuatu dari perutnya", "16:69"),
        ("ayat mengenai kapal yang berlayar di laut", "31:31"),
    ],
)
async def test_unseen_semantic_queries_are_forwarded_to_search_then_content(
    unseen_query, provider_key
):
    search_queries: list[str] = []
    content_keys: list[str] = []

    def handler(request: httpx.Request):
        if request.url.path == "/oauth2/token":
            scope = parse_qs(request.content.decode())["scope"][0]
            return httpx.Response(
                200,
                json={"access_token": f"{scope}-token", "expires_in": 3600},
            )
        assert request.headers["x-client-id"] == "fixture-client"
        if request.url.path == "/content/api/v4/chapters":
            return httpx.Response(200, json={"chapters": CHAPTERS})
        if request.url.path == "/content/api/v4/resources/translations":
            return httpx.Response(200, json=_translation_payload())
        if request.url.path == "/search/api/v1/search":
            assert request.headers["x-auth-token"] == "search-token"
            search_queries.append(request.url.params["query"])
            assert request.url.params["translation_ids"] == "9876"
            return httpx.Response(
                200,
                json={
                    "pagination": {"current_page": 1, "total_records": 1},
                    "result": {
                        "navigation": [],
                        "verses": [
                            {
                                "result_type": "ayah",
                                "key": provider_key,
                                "name": "provider fixture",
                            }
                        ],
                    },
                },
            )
        if request.url.path.startswith("/content/api/v4/verses/by_key/"):
            key = request.url.path.rsplit("/", 1)[-1]
            content_keys.append(key)
            return httpx.Response(200, json=_verse_payload(key))
        raise AssertionError(f"Unexpected request: {request.url}")

    provider = QuranProvider(transport=httpx.MockTransport(handler))
    claim, queries = _query_bundle(unseen_query)
    result = await provider.retrieve(claim.source_text or "", queries)

    assert result.mode == RetrievalMode.SEMANTIC_SEARCH
    assert search_queries
    assert any(
        token in " ".join(search_queries).casefold()
        for token in unseen_query.casefold().split()
        if len(token) > 5
    )
    assert content_keys == [provider_key]
    assert result.candidates[0].verse_key == provider_key
    assert result.candidates[0].retrieval_mode == RetrievalMode.SEMANTIC_SEARCH
    # The verse key comes solely from mocked provider search, never a query map.
    assert provider_key not in " ".join(queries.all_queries)


@pytest.mark.asyncio
async def test_missing_credentials_fails_before_any_network_request(monkeypatch):
    monkeypatch.setattr(settings, "quran_foundation_client_id", None)
    monkeypatch.setattr(settings, "quran_foundation_client_secret", None)
    called = False

    def handler(request: httpx.Request):
        nonlocal called
        called = True
        return httpx.Response(500)

    provider = QuranProvider(transport=httpx.MockTransport(handler))
    claim, queries = _query_bundle("carikan Al-Baqarah ayat 255")
    with pytest.raises(QuranProviderUnavailable, match="not configured"):
        await provider.retrieve(claim.source_text or "", queries)
    assert called is False


@pytest.mark.asyncio
async def test_translation_selection_uses_content_language_not_localized_label():
    def handler(request: httpx.Request):
        if request.url.path == "/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "content-token", "expires_in": 3600},
            )
        if request.url.path == "/content/api/v4/resources/translations":
            return httpx.Response(
                200,
                json={
                    "translations": [
                        {
                            "id": 1,
                            "name": "English fixture",
                            "language_name": "english",
                            "translated_name": {
                                "name": "Bahasa Inggris",
                                "language_name": "indonesian",
                            },
                        },
                        {
                            "id": 2,
                            "name": "Indonesian fixture",
                            "language_name": "indonesian",
                            "translated_name": {
                                "name": "Bahasa Indonesia",
                                "language_name": "indonesian",
                            },
                        },
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    provider = QuranProvider(transport=httpx.MockTransport(handler))
    resource = await provider.get_indonesian_translation()

    assert resource is not None
    assert resource.resource_id == 2
    assert resource.language_name == "indonesian"


@pytest.mark.asyncio
async def test_exact_reference_degrades_to_arabic_when_translation_metadata_fails():
    translation_attempts = 0

    def handler(request: httpx.Request):
        nonlocal translation_attempts
        if request.url.path == "/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "content-token", "expires_in": 3600},
            )
        if request.url.path == "/content/api/v4/chapters":
            return httpx.Response(200, json={"chapters": CHAPTERS})
        if request.url.path == "/content/api/v4/resources/translations":
            translation_attempts += 1
            return httpx.Response(503)
        if request.url.path == "/content/api/v4/verses/by_key/2:255":
            assert "translations" not in request.url.params
            return httpx.Response(200, json=_verse_payload("2:255"))
        raise AssertionError(f"Unexpected request: {request.url}")

    provider = QuranProvider(transport=httpx.MockTransport(handler))
    claim, queries = _query_bundle("carikan Al-Baqarah ayat 255")
    result = await provider.retrieve(claim.source_text or "", queries)

    assert translation_attempts == 3
    assert result.candidates[0].retrieved_texts.get("ar")
    assert "id" not in result.candidates[0].retrieved_texts
    assert result.errors


@pytest.mark.asyncio
async def test_unapproved_search_scope_is_negatively_cached_without_secret_leak():
    token_attempts = 0

    def handler(request: httpx.Request):
        nonlocal token_attempts
        if request.url.path == "/oauth2/token":
            token_attempts += 1
            return httpx.Response(
                400,
                json={"error": "invalid_scope", "error_description": "not approved"},
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    provider = QuranProvider(transport=httpx.MockTransport(handler))
    for _ in range(2):
        with pytest.raises(QuranProviderError, match="invalid_scope") as error:
            await provider._tokens.get("search")
        assert "fixture-secret" not in str(error.value)

    assert token_attempts == 1


@pytest.mark.asyncio
async def test_semantic_batch_reports_one_cached_invalid_scope_error():
    token_attempts: dict[str, int] = {"content": 0, "search": 0}

    def handler(request: httpx.Request):
        if request.url.path == "/oauth2/token":
            scope = parse_qs(request.content.decode())["scope"][0]
            token_attempts[scope] += 1
            if scope == "search":
                return httpx.Response(400, json={"error": "invalid_scope"})
            return httpx.Response(
                200,
                json={"access_token": "content-token", "expires_in": 3600},
            )
        if request.url.path == "/content/api/v4/chapters":
            return httpx.Response(200, json={"chapters": CHAPTERS})
        if request.url.path == "/content/api/v4/resources/translations":
            return httpx.Response(200, json=_translation_payload())
        raise AssertionError(f"Unexpected request: {request.url}")

    provider = QuranProvider(transport=httpx.MockTransport(handler))
    claim, queries = _query_bundle(
        "ayat tentang pergantian malam dan siang sebagai tanda"
    )
    result = await provider.retrieve(claim.source_text or "", queries)

    assert result.candidates == []
    assert result.mode == RetrievalMode.SEMANTIC_SEARCH
    assert len([error for error in result.errors if "invalid_scope" in error]) == 1
    assert token_attempts == {"content": 1, "search": 1}


@pytest.mark.asyncio
async def test_token_is_cached_per_scope_and_401_is_retried_once():
    token_requests: list[str] = []
    content_attempts = 0

    def handler(request: httpx.Request):
        nonlocal content_attempts
        if request.url.path == "/oauth2/token":
            scope = parse_qs(request.content.decode())["scope"][0]
            token_requests.append(scope)
            return httpx.Response(
                200,
                json={
                    "access_token": f"{scope}-token-{token_requests.count(scope)}",
                    "expires_in": 3600,
                },
            )
        if request.url.path == "/content/api/v4/chapters":
            content_attempts += 1
            if content_attempts == 1:
                return httpx.Response(401, json={"message": "expired"})
            return httpx.Response(200, json={"chapters": CHAPTERS})
        raise AssertionError(f"Unexpected request: {request.url}")

    provider = QuranProvider(transport=httpx.MockTransport(handler))
    first = await provider.list_chapters()
    second = await provider.list_chapters()

    assert first == second
    assert content_attempts == 2
    assert token_requests == ["content", "content"]


@pytest.mark.asyncio
async def test_token_with_missing_requested_scope_is_rejected():
    def handler(request: httpx.Request):
        if request.url.path == "/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "wrong-scope-token",
                    "expires_in": 3600,
                    "scope": "search",
                },
            )
        raise AssertionError("Content request must not run with the wrong scope.")

    provider = QuranProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(QuranProviderError, match="requested scope"):
        await provider.list_chapters()
