from __future__ import annotations

import pytest

from sanad_core.intent import IntentEngine
from sanad_core.query_generator import QueryGenerator
from sanad_core.quran_reference import detect_exact_reference
from sanad_core.schemas import Domain, RoutingMethod


def _local_components():
    engine = IntentEngine()
    engine._client = None
    generator = QueryGenerator()
    generator._client = None
    return engine, generator


@pytest.mark.parametrize(
    "text",
    [
        "apakah benar tentang dalil bahwa semua hal harus berawal dari niat",
        "aku lupa persisnya, tapi katanya amal itu tergantung niat",
        "katanya orang mencari ilmu dimudahkan jalan ke surga",
    ],
)
def test_semantic_hadith_inputs_route_without_explicit_keyword(text):
    engine, generator = _local_components()
    intent = engine.analyze(text)
    claim = engine.reconstruct(intent)
    queries = generator.generate(claim)

    assert intent.domain_candidate == Domain.HADITH
    assert intent.routing_method == RoutingMethod.LOCAL_SEMANTIC
    assert intent.routing_confidence >= 0.58
    assert intent.needs_clarification is False
    assert claim.domain == Domain.HADITH
    assert len(queries.indonesian_queries) >= 2
    assert queries.english_queries
    assert queries.arabic_queries


def test_claim_reconstruction_for_intention_relationship_is_indonesian_and_semantic():
    engine, generator = _local_components()
    claim = engine.reconstruct(
        engine.analyze(
            "apakah benar tentang dalil bahwa semua hal harus berawal dari niat"
        )
    )
    assert claim.reconstructed_claim == (
        "Mencari hadis atau dalil yang menyatakan bahwa amal/perbuatan "
        "berkaitan dengan niat."
    )
    assert "intentions" in generator.generate(claim).english_queries


@pytest.mark.parametrize(
    "text,verse_number,chapter_number,chapter_name",
    [
        ("carikan Al-Baqarah ayat 255", 255, None, "Al-Baqarah"),
        ("2:255", 255, 2, None),
        ("carikan surat Al-Ikhlas ayat 1", 1, None, "Al-Ikhlas"),
    ],
)
def test_exact_quran_reference_detection_is_programmatic(
    text, verse_number, chapter_number, chapter_name
):
    reference = detect_exact_reference(text)
    assert reference is not None
    assert reference.verse_number == verse_number
    assert reference.chapter_number == chapter_number
    assert reference.chapter_name == chapter_name


@pytest.mark.parametrize(
    "text",
    [
        "carikan Al-Baqarah ayat 255",
        "carikan surat Al-Ikhlas ayat 1",
        "ayat tentang Allah tidak membebani seseorang di luar kemampuannya",
        "ayat tentang berbakti kepada orang tua",
    ],
)
def test_quran_queries_route_to_quran_without_forcing_hadith(text):
    engine, generator = _local_components()
    intent = engine.analyze(text)
    claim = engine.reconstruct(intent)
    bundle = generator.generate(claim)

    assert intent.domain_candidate == Domain.QURAN
    assert intent.needs_clarification is False
    assert claim.domain == Domain.QURAN
    assert bundle.indonesian_queries
    # Query generation never guesses a verse key for a semantic input.
    if detect_exact_reference(text) is None:
        assert not any(":" in query for query in bundle.all_queries)


def test_wrong_bukhari_attribution_does_not_override_explicit_quran_target():
    engine, generator = _local_components()
    text = "Kayaknya dari Bukhari, tapi ayat tentang kasih sayang itu ada di mana?"
    intent = engine.analyze(text)
    claim = engine.reconstruct(intent)
    bundle = generator.generate(claim)

    assert intent.domain_candidate == Domain.QURAN
    assert claim.user_attribution_hypothesis == "Sahih al-Bukhari"
    assert bundle.attribution_neutral_queries
    assert "bukhari" not in bundle.attribution_neutral_queries[0].casefold()
    assert "bukhari" in bundle.attribution_signal_queries[-1].casefold()


def test_tentative_surah_attribution_is_hypothesis_not_a_reference():
    engine, _ = _local_components()
    text = "Kayaknya Al-Baqarah, tapi saya mencari hadis tentang niat."
    intent = engine.analyze(text)
    claim = engine.reconstruct(intent)

    assert intent.domain_candidate == Domain.HADITH
    assert claim.user_attribution_hypothesis == "Qur'an: Al-Baqarah"


def test_dual_domain_request_asks_clarification_without_choosing_one():
    engine, _ = _local_components()
    intent = engine.analyze("ada hadis atau ayat tentang sabar?")

    assert intent.domain_candidate == Domain.GENERAL_ISLAMIC
    assert intent.needs_clarification is True
    assert "hadis" in (intent.clarification_question or "").casefold()
    assert "al-qur'an" in (intent.clarification_question or "").casefold()


def test_unrelated_query_is_unknown_and_not_religiously_expanded():
    engine, _ = _local_components()
    intent = engine.analyze("bagaimana memperbaiki koneksi Wi-Fi laptop saya?")

    assert intent.domain_candidate == Domain.UNKNOWN
    assert intent.routing_method == RoutingMethod.OUT_OF_SCOPE
    assert intent.needs_clarification is False


def test_openai_is_not_enabled_even_if_legacy_keys_exist(monkeypatch):
    from sanad_core import intent as intent_module
    from sanad_core import query_generator as query_module

    monkeypatch.setattr(intent_module.settings, "openai_api_key", "must-not-be-used")
    monkeypatch.setattr(intent_module.settings, "openai_model", "must-not-be-used")
    monkeypatch.setattr(intent_module.settings, "sanad_enable_remote_semantic", False)
    monkeypatch.setattr(query_module.settings, "sanad_enable_remote_semantic", False)

    assert IntentEngine()._client is None
    assert QueryGenerator()._client is None
