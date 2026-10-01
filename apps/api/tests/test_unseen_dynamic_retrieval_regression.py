from __future__ import annotations

import re
from urllib.parse import parse_qs

import httpx
import pytest

from sanad_core.config import settings
from sanad_core.intent import IntentEngine
from sanad_core.providers.quran import QuranProvider
from sanad_core.quran_reference import detect_exact_reference
from sanad_core.query_generator import QueryGenerator
from sanad_core.schemas import Domain, RetrievalMode, RoutingMethod


HADITH_BLIND_CASES = [
    (
        "ada hadis gak yang membahas orang terbaik itu yang paling baik "
        "akhlaknya?",
        {"akhlak"},
    ),
    (
        "aku ingat samar-samar ada hadis soal senyum itu sedekah",
        {"senyum", "sedekah"},
    ),
    (
        "dalil soal kuat itu bukan menang gulat tapi bisa menahan marah",
        {"kuat", "menahan", "marah"},
    ),
]

QURAN_PROMPT_CASES = [
    ("carikan ayat tentang larangan berkata ah kepada orang tua", "larangan"),
    ("ada ayat yang membahas hujan menghidupkan bumi yang mati?", "hujan"),
    ("ayat tentang manusia diciptakan berbangsa-bangsa", "berbangsa"),
    ("carikan surat Maryam ayat 12", "maryam"),
]

# This case is intentionally absent from the upgrade prompt and from production
# mappings. The test never supplies an expected religious answer for it.
RANDOM_QURAN_BLIND_QUERY = "carikan ayat mengenai bayangan yang dipanjangkan"

# This deliberately arbitrary key is returned by the fake Search API for every
# semantic query. It is not an assertion about the correct ayah for any topic.
PROVIDER_ONLY_VERSE_KEY = "61:9"
TRANSLATION_RESOURCE_ID = 73001

PROVIDER_CHAPTERS = [
    {
        "id": 19,
        "name_simple": "Maryam",
        "name_arabic": "مريم",
        "verses_count": 98,
    },
    {
        "id": 61,
        "name_simple": "Provider-Sentinel",
        "name_arabic": "سورة تجريبية",
        "verses_count": 14,
    },
]


def _local_pipeline() -> tuple[IntentEngine, QueryGenerator]:
    intent = IntentEngine()
    intent._client = None
    queries = QueryGenerator()
    queries._client = None
    return intent, queries


def _translation_resources_payload() -> dict:
    return {
        "translations": [
            {
                "id": 99,
                "name": "English fixture",
                "language_name": "english",
            },
            {
                "id": TRANSLATION_RESOURCE_ID,
                "name": "Terjemahan Indonesia dari metadata fake provider",
                "language_name": "indonesian",
            },
        ]
    }


def _verse_payload(verse_key: str) -> dict:
    chapter_number, verse_number = (int(part) for part in verse_key.split(":"))
    return {
        "verse": {
            "chapter_id": chapter_number,
            "verse_number": verse_number,
            "verse_key": verse_key,
            "text_uthmani": f"نص عربي من المزود {verse_key}",
            "translations": [
                {
                    "resource_id": TRANSLATION_RESOURCE_ID,
                    "resource_name": "Terjemahan Indonesia dari metadata fake provider",
                    "language_name": "indonesian",
                    "text": f"Terjemahan Indonesia fixture untuk {verse_key}",
                }
            ],
        }
    }


@pytest.fixture(autouse=True)
def _quran_provider_credentials(monkeypatch):
    monkeypatch.setattr(settings, "quran_foundation_client_id", "fixture-client")
    monkeypatch.setattr(settings, "quran_foundation_client_secret", "fixture-secret")
    monkeypatch.setattr(settings, "sanad_quran_max_results", 5)


@pytest.mark.parametrize("raw_user_input,required_concepts", HADITH_BLIND_CASES)
def test_blind_hadith_examples_route_and_generate_semantic_queries(
    raw_user_input: str,
    required_concepts: set[str],
):
    intent_engine, query_generator = _local_pipeline()

    intent = intent_engine.analyze(raw_user_input)
    claim = intent_engine.reconstruct(intent)
    queries = query_generator.generate(claim)

    assert intent.domain_candidate == Domain.HADITH
    assert intent.routing_confidence >= 0.58
    assert intent.needs_clarification is False
    assert claim.domain == Domain.HADITH
    assert queries.indonesian_queries
    assert queries.english_queries
    assert queries.arabic_queries
    assert 1 <= len(queries.web_queries) <= 2

    generated = " ".join(queries.all_queries).casefold()
    assert required_concepts <= set(re.findall(r"[\w-]+", generated))
    assert all("https://" not in query for query in queries.all_queries)
    assert any("site:" not in query.casefold() for query in queries.web_queries)


@pytest.mark.parametrize(
    "raw_user_input,concept_marker",
    [*QURAN_PROMPT_CASES, (RANDOM_QURAN_BLIND_QUERY, "bayangan")],
)
def test_blind_quran_examples_route_without_guessing_a_verse_key(
    raw_user_input: str,
    concept_marker: str,
):
    intent_engine, query_generator = _local_pipeline()

    intent = intent_engine.analyze(raw_user_input)
    claim = intent_engine.reconstruct(intent)
    queries = query_generator.generate(claim)

    assert intent.domain_candidate == Domain.QURAN
    assert intent.needs_clarification is False
    assert claim.domain == Domain.QURAN
    assert queries.indonesian_queries
    assert 1 <= len(queries.web_queries) <= 2
    assert concept_marker in " ".join(queries.all_queries).casefold()

    if detect_exact_reference(raw_user_input) is None:
        assert not any(
            re.search(r"(?<!\d)\d{1,3}:\d{1,3}(?!\d)", query)
            for query in queries.all_queries
        )


@pytest.mark.parametrize(
    "raw_user_input,chapter_number,chapter_name,verse_number",
    [
        ("2:255", 2, None, 255),
        ("carikan Al-Baqarah ayat 255", None, "Al-Baqarah", 255),
        ("surat Al-Ikhlas ayat 1", None, "Al-Ikhlas", 1),
        ("carikan surat Maryam ayat 12", None, "Maryam", 12),
    ],
)
def test_exact_quran_references_are_parsed_programmatically(
    raw_user_input: str,
    chapter_number: int | None,
    chapter_name: str | None,
    verse_number: int,
):
    reference = detect_exact_reference(raw_user_input)

    assert reference is not None
    assert reference.chapter_number == chapter_number
    assert reference.chapter_name == chapter_name
    assert reference.verse_number == verse_number


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_user_input",
    [
        QURAN_PROMPT_CASES[0][0],
        QURAN_PROMPT_CASES[1][0],
        QURAN_PROMPT_CASES[2][0],
        RANDOM_QURAN_BLIND_QUERY,
    ],
)
async def test_semantic_quran_blind_cases_use_provider_search_then_content(
    raw_user_input: str,
):
    search_queries: list[str] = []
    fetched_verse_keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            scope = parse_qs(request.content.decode())["scope"][0]
            return httpx.Response(
                200,
                json={"access_token": f"{scope}-fixture-token", "expires_in": 3600},
            )
        if request.url.path == "/content/api/v4/chapters":
            return httpx.Response(200, json={"chapters": PROVIDER_CHAPTERS})
        if request.url.path == "/content/api/v4/resources/translations":
            return httpx.Response(200, json=_translation_resources_payload())
        if request.url.path == "/search/api/v1/search":
            search_queries.append(request.url.params["query"])
            assert request.url.params["translation_ids"] == str(
                TRANSLATION_RESOURCE_ID
            )
            return httpx.Response(
                200,
                json={
                    "result": {
                        "navigation": [],
                        "verses": [
                            {
                                "result_type": "ayah",
                                "key": PROVIDER_ONLY_VERSE_KEY,
                                "name": "fake-provider-only-candidate",
                            }
                        ],
                    }
                },
            )
        if request.url.path.startswith("/content/api/v4/verses/by_key/"):
            verse_key = request.url.path.rsplit("/", 1)[-1]
            fetched_verse_keys.append(verse_key)
            return httpx.Response(200, json=_verse_payload(verse_key))
        raise AssertionError(f"Unexpected fake-provider request: {request.url}")

    intent_engine, query_generator = _local_pipeline()
    claim = intent_engine.reconstruct(intent_engine.analyze(raw_user_input))
    queries = query_generator.generate(claim)
    assert PROVIDER_ONLY_VERSE_KEY not in raw_user_input
    assert PROVIDER_ONLY_VERSE_KEY not in " ".join(queries.all_queries)

    provider = QuranProvider(
        transport=httpx.MockTransport(handler),
        environment="prelive",
    )
    result = await provider.retrieve(raw_user_input, queries)

    assert result.mode == RetrievalMode.SEMANTIC_SEARCH
    assert result.errors == []
    assert search_queries
    assert set(search_queries) <= set(queries.all_queries)
    assert fetched_verse_keys == [PROVIDER_ONLY_VERSE_KEY]
    assert [candidate.verse_key for candidate in result.candidates] == [
        PROVIDER_ONLY_VERSE_KEY
    ]
    assert result.candidates[0].retrieved_texts["ar"].startswith("نص عربي")
    assert result.candidates[0].retrieved_texts["id"].startswith(
        "Terjemahan Indonesia fixture"
    )


@pytest.mark.asyncio
async def test_maryam_exact_reference_fetches_content_without_search():
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "content-fixture-token", "expires_in": 3600},
            )
        if request.url.path == "/content/api/v4/chapters":
            return httpx.Response(200, json={"chapters": PROVIDER_CHAPTERS})
        if request.url.path == "/content/api/v4/resources/translations":
            return httpx.Response(200, json=_translation_resources_payload())
        if request.url.path == "/content/api/v4/verses/by_key/19:12":
            return httpx.Response(200, json=_verse_payload("19:12"))
        raise AssertionError(f"Unexpected fake-provider request: {request.url}")

    raw_user_input = "carikan surat Maryam ayat 12"
    intent_engine, query_generator = _local_pipeline()
    claim = intent_engine.reconstruct(intent_engine.analyze(raw_user_input))
    queries = query_generator.generate(claim)

    provider = QuranProvider(
        transport=httpx.MockTransport(handler),
        environment="prelive",
    )
    result = await provider.retrieve(raw_user_input, queries)

    assert result.mode == RetrievalMode.EXACT_REFERENCE
    assert [candidate.verse_key for candidate in result.candidates] == ["19:12"]
    assert result.candidates[0].surah_name == "Maryam"
    assert "/content/api/v4/chapters" in requested_paths
    assert "/content/api/v4/verses/by_key/19:12" in requested_paths
    assert not any(path.startswith("/search/") for path in requested_paths)


def test_materially_ambiguous_religious_query_requests_clarification():
    intent_engine, _ = _local_pipeline()

    intent = intent_engine.analyze("ada hadis atau ayat tentang sabar?")

    assert intent.domain_candidate == Domain.GENERAL_ISLAMIC
    assert intent.needs_clarification is True
    assert intent.clarification_question


def test_general_islamic_query_is_not_demoted_to_unknown():
    intent_engine, _ = _local_pipeline()

    intent = intent_engine.analyze("jelaskan perbedaan fikih dan akidah")

    assert intent.domain_candidate == Domain.GENERAL_ISLAMIC
    assert intent.routing_method == RoutingMethod.LOCAL_SEMANTIC


def test_unrelated_query_remains_out_of_scope():
    intent_engine, _ = _local_pipeline()

    intent = intent_engine.analyze("tolong rekomendasikan laptop untuk desain grafis")

    assert intent.domain_candidate == Domain.UNKNOWN
    assert intent.routing_method == RoutingMethod.OUT_OF_SCOPE
    assert intent.needs_clarification is False
