from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from sanad_core.config import Settings, settings
from sanad_core.providers.broad_web import AsyncTTLCache
from sanad_core.providers.hadithapi import HadithAPIProvider, HadithAPISearchRequest
from sanad_core.providers.quran import QuranProvider
from sanad_core.schemas import QueryBundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _hadith_payload(*, records: list[dict] | None = None) -> dict:
    if records is None:
        records = [
            {
                "id": 73,
                "hadithNumber": "9",
                "hadithEnglish": "A provider fixture about patience.",
                "hadithArabic": "نص تجريبي عن الصبر",
                "bookSlug": "sahih-muslim",
                "status": "Sahih",
                "book": {
                    "bookName": "Synthetic Collection",
                    "bookSlug": "sahih-muslim",
                },
            }
        ]
    return {"hadiths": {"data": records}}


@pytest.mark.asyncio
async def test_hadithapi_duplicate_request_uses_cache_and_returns_isolated_copy(
    monkeypatch,
):
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.url.params["apiKey"] == "hadith-cache-secret"
        return httpx.Response(200, json=_hadith_payload())

    monkeypatch.setattr(settings, "hadith_api_key", "hadith-cache-secret")
    cache = AsyncTTLCache(ttl_seconds=60)
    provider = HadithAPIProvider(
        transport=httpx.MockTransport(handler),
        cache=cache,
    )
    request = HadithAPISearchRequest(hadith_english="patience")

    first = await provider.search(request, retrieval_queries=["hadith about patience"])
    first[0].title = "mutated by caller"
    second = await provider.search(request, retrieval_queries=["hadith about patience"])

    assert request_count == 1
    assert second[0].title == "Synthetic Collection"
    assert "hadith-cache-secret" not in repr(first)
    assert "hadith-cache-secret" not in repr(second)


@pytest.mark.asyncio
async def test_hadithapi_empty_response_is_not_cached(monkeypatch):
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        records = [] if request_count == 1 else None
        return httpx.Response(200, json=_hadith_payload(records=records))

    monkeypatch.setattr(settings, "hadith_api_key", "hadith-cache-secret")
    provider = HadithAPIProvider(transport=httpx.MockTransport(handler))
    request = HadithAPISearchRequest(hadith_english="patience")

    assert await provider.search(request) == []
    recovered = await provider.search(request)

    assert request_count == 2
    assert len(recovered) == 1


@pytest.mark.asyncio
async def test_quran_duplicate_exact_retrieval_uses_result_cache(monkeypatch):
    request_counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        request_counts[path] = request_counts.get(path, 0) + 1
        if path == "/oauth2/token":
            authorization = request.headers["authorization"]
            assert authorization.startswith("Basic ")
            assert "quran-cache-secret" not in authorization
            return httpx.Response(
                200,
                json={"access_token": "short-lived-test-token", "expires_in": 3600},
            )
        assert request.headers["x-client-id"] == "quran-cache-client"
        assert request.headers["x-auth-token"] == "short-lived-test-token"
        if path == "/content/api/v4/chapters":
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
        if path == "/content/api/v4/resources/translations":
            return httpx.Response(
                200,
                json={
                    "translations": [
                        {
                            "id": 999,
                            "name": "Terjemahan Indonesia Fixture",
                            "language_name": "indonesian",
                        }
                    ]
                },
            )
        if path == "/content/api/v4/verses/by_key/2:255":
            return httpx.Response(
                200,
                json={
                    "verse": {
                        "chapter_id": 2,
                        "verse_number": 255,
                        "verse_key": "2:255",
                        "text_uthmani": "نص عربي تجريبي",
                        "translations": [
                            {
                                "resource_id": 999,
                                "text": "Terjemahan Indonesia terstruktur.",
                            }
                        ],
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    monkeypatch.setattr(
        settings, "quran_foundation_client_id", "quran-cache-client"
    )
    monkeypatch.setattr(
        settings, "quran_foundation_client_secret", "quran-cache-secret"
    )
    provider = QuranProvider(
        transport=httpx.MockTransport(handler),
        cache=AsyncTTLCache(ttl_seconds=60),
    )
    queries = QueryBundle(indonesian_queries=["Al-Baqarah ayat 255"])

    first = await provider.retrieve("carikan Al-Baqarah ayat 255", queries)
    first.candidates[0].title = "mutated by caller"
    second = await provider.retrieve("carikan Al-Baqarah ayat 255", queries)

    assert sum(request_counts.values()) == 4
    assert request_counts["/oauth2/token"] == 1
    assert request_counts["/content/api/v4/verses/by_key/2:255"] == 1
    assert second.candidates[0].title == "Surah Al-Baqarah 2:255"
    serialized = repr(second)
    assert "quran-cache-secret" not in serialized
    assert "short-lived-test-token" not in serialized


def test_structured_provider_default_cache_uses_knowledge_ttl(monkeypatch):
    monkeypatch.setattr(settings, "sanad_knowledge_cache_ttl_seconds", 4321)

    hadith = HadithAPIProvider()
    quran = QuranProvider()

    assert hadith._cache.ttl_seconds == 4321
    assert quran._result_cache.ttl_seconds == 4321


def test_v2_public_provider_config_fields_load_from_environment(monkeypatch):
    monkeypatch.setenv("WIKIPEDIA_LANGS", "en,id")
    monkeypatch.setenv("OPENALEX_API_KEY", "openalex-config-secret")
    monkeypatch.setenv("CROSSREF_MAILTO", "contact@example.test")
    monkeypatch.setenv("CROSSREF_USER_AGENT", "SANAD.AI-Test/0.2")
    monkeypatch.setenv("SANAD_KNOWLEDGE_CACHE_TTL_SECONDS", "1234")

    loaded = Settings(_env_file=None)

    assert loaded.wikipedia_langs == "en,id"
    assert loaded.openalex_api_key == "openalex-config-secret"
    assert loaded.crossref_mailto == "contact@example.test"
    assert loaded.crossref_user_agent == "SANAD.AI-Test/0.2"
    assert loaded.sanad_knowledge_cache_ttl_seconds == 1234


def test_check_setup_reports_only_credential_presence(tmp_path):
    secret_values = {
        "OPENAI_API_KEY": "openai-setup-secret",
        "OPENAI_MODEL": "private-model-name",
        "BRAVE_SEARCH_API_KEY": "brave-setup-secret",
        "HADITH_API_KEY": "hadith-setup-secret",
        "SUNNAH_API_KEY": "sunnah-setup-secret",
        "QURAN_FOUNDATION_CLIENT_ID": "quran-private-client",
        "QURAN_FOUNDATION_CLIENT_SECRET": "quran-setup-secret",
        "OPENALEX_API_KEY": "openalex-setup-secret",
        "CROSSREF_MAILTO": "private-contact@example.test",
    }
    environment = {
        "PYTHONPATH": str(PROJECT_ROOT),
        "WIKIPEDIA_LANGS": "id,en",
        "CROSSREF_USER_AGENT": "SANAD.AI-Test/0.2",
        **secret_values,
    }

    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "check_setup.py")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    output = completed.stdout
    for variable in secret_values:
        assert f"{variable}: CONFIGURED" in output
    for secret in secret_values.values():
        assert secret not in output
    assert "WIKIPEDIA_LANGS: id,en" in output
    assert "CROSSREF_USER_AGENT: SANAD.AI-Test/0.2" in output


def test_env_example_keeps_all_credentials_blank():
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    configured = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    sensitive = {
        "OPENAI_API_KEY",
        "BRAVE_SEARCH_API_KEY",
        "HADITH_API_KEY",
        "SUNNAH_API_KEY",
        "QURAN_FOUNDATION_CLIENT_ID",
        "QURAN_FOUNDATION_CLIENT_SECRET",
        "OPENALEX_API_KEY",
        "CROSSREF_MAILTO",
    }

    assert sensitive <= configured.keys()
    assert all(configured[key] == "" for key in sensitive)
