from __future__ import annotations

import re

import pytest

from sanad_core.concept_expansion import ConceptExpansionEngine
from sanad_core.intent import IntentEngine
from sanad_core.query_generator import QueryGenerator
from sanad_core.schemas import Domain, RoutingMethod


@pytest.mark.parametrize(
    "text,canonical,english_marker,arabic_marker",
    [
        ("hadis tentang niat", "niat", "intention", "النية"),
        ("ayat tentang sabar", "sabar", "patience", "الصبر"),
        ("dalil mengenai rezeki", "rezeki", "provision", "الرزق"),
        ("sabda tentang mencari ilmu", "ilmu", "knowledge", "العلم"),
        ("menahan marah", "marah", "anger", "الغضب"),
        ("berbakti kepada orang tua", "orang_tua", "parents", "الوالدين"),
        ("mengingat kematian", "kematian", "death", "الموت"),
        ("senyum dan sedekah", "sedekah", "charity", "الصدقة"),
        ("akhlak yang baik", "akhlak", "character", "الأخلاق"),
        ("menjaga hak tetangga", "tetangga", "neighbor", "الجار"),
    ],
)
def test_concept_engine_expands_core_topics_without_answer_mappings(
    text: str,
    canonical: str,
    english_marker: str,
    arabic_marker: str,
):
    expansion = ConceptExpansionEngine().expand(text)

    assert canonical in expansion.matched_concepts
    assert any(english_marker in term.casefold() for term in expansion.english_terms)
    assert any(arabic_marker in term for term in expansion.arabic_terms)
    assert expansion.indonesian_phrases
    assert expansion.english_phrases
    assert expansion.arabic_phrases

    generated = " ".join(expansion.all_terms).casefold()
    assert "http://" not in generated
    assert "https://" not in generated
    assert not re.search(r"(?<!\d)\d{1,3}:\d{1,4}(?!\d)", generated)


def test_death_expansion_is_semantic_not_just_a_literal_duplicate():
    expansion = ConceptExpansionEngine().expand("ada hadis tentang kematian?")

    assert {"kematian", "mengingat kematian", "ajal", "kubur"} <= set(
        expansion.indonesian_terms
    )
    assert {"death", "remember death", "remembrance of death"} <= set(
        expansion.english_terms
    )
    assert {"الموت", "ذكر الموت", "الأجل", "القبر"} <= set(
        expansion.arabic_terms
    )


def test_post_blind_neighbor_query_gets_multilingual_retrieval_terms_only():
    """Regression captured after the unseen query exposed a vocabulary gap."""

    engine = IntentEngine()
    claim = engine.reconstruct(
        engine.analyze("ada hadis tentang menjaga tetangga dari gangguan?")
    )
    queries = QueryGenerator().generate(claim)

    assert claim.domain == Domain.HADITH
    assert any("neighbor" in query.casefold() for query in queries.english_queries)
    assert any("الجار" in query for query in queries.arabic_queries)
    joined = " ".join(queries.all_queries)
    assert "http://" not in joined and "https://" not in joined
    assert not re.search(r"(?<!\d)\d{1,3}:\d{1,4}(?!\d)", joined)


def test_remembered_death_paraphrase_can_route_without_exact_hadith_keyword():
    intent = IntentEngine().analyze(
        "katanya kita perlu sering mengingat kematian, sumbernya dari mana?"
    )

    assert intent.domain_candidate == Domain.HADITH
    assert intent.routing_method == RoutingMethod.LOCAL_SEMANTIC
    assert intent.needs_clarification is False


def test_unseen_concepts_are_retained_dynamically_without_guessed_arabic():
    expansion = ConceptExpansionEngine().expand(
        "bagaimana tradisi manuskrip Timbuktu berkembang dalam Islam?"
    )

    assert "timbuktu" in expansion.unknown_terms
    assert any("timbuktu" in phrase.casefold() for phrase in expansion.indonesian_phrases)
    assert any("timbuktu" in phrase.casefold() for phrase in expansion.english_phrases)
    # A name without a local high-confidence Arabic form is not transliterated.
    assert all("timbuktu" not in phrase.casefold() for phrase in expansion.arabic_phrases)


@pytest.mark.parametrize(
    "text",
    [
        "bagaimana sejarah Perang Badar?",
        "siapa Salahuddin Al-Ayyubi?",
        "bagaimana Dinasti Abbasiyah berkembang?",
        "bagaimana tradisi manuskrip Timbuktu berkembang dalam Islam?",
        "bagaimana sejarah kodifikasi Al-Qur'an?",
        "bagaimana berkembangnya Baitul Hikmah di Baghdad?",
    ],
)
def test_islamic_history_queries_route_to_history(text: str):
    intent = IntentEngine().analyze(text)

    assert intent.domain_candidate == Domain.ISLAMIC_HISTORY
    assert intent.routing_method in {RoutingMethod.RULE_BASED, RoutingMethod.LOCAL_SEMANTIC}
    assert intent.routing_confidence >= 0.58
    assert intent.needs_clarification is False


@pytest.mark.parametrize(
    "text",
    [
        "ada penelitian akademik tentang perkembangan ilmu hadis?",
        "carikan jurnal ilmiah tentang studi Al-Qur'an di Indonesia",
        "is there scholarly research on Islamic jurisprudence?",
    ],
)
def test_academic_queries_route_to_academic_islamic_studies(text: str):
    intent = IntentEngine().analyze(text)

    assert intent.domain_candidate == Domain.ACADEMIC_ISLAMIC_STUDIES
    assert intent.routing_confidence >= 0.58
    assert intent.needs_clarification is False


@pytest.mark.parametrize(
    "text,domain,marker",
    [
        ("ada hadis tentang kematian?", Domain.HADITH, "kematian"),
        ("ada sabda tentang menahan marah?", Domain.HADITH, "marah"),
        ("bagaimana sejarah Perang Badar?", Domain.ISLAMIC_HISTORY, "badar"),
        (
            "ada penelitian akademik tentang perkembangan ilmu hadis?",
            Domain.ACADEMIC_ISLAMIC_STUDIES,
            "ilmu",
        ),
    ],
)
def test_query_generator_emits_independent_multilingual_retrieval_queries(
    text: str,
    domain: Domain,
    marker: str,
):
    engine = IntentEngine()
    generator = QueryGenerator()
    intent = engine.analyze(text)
    claim = engine.reconstruct(intent)
    queries = generator.generate(claim)

    assert claim.domain == domain
    assert queries.indonesian_queries
    assert queries.english_queries
    assert 1 <= len(queries.web_queries) <= 2
    assert marker in " ".join(queries.all_queries + queries.web_queries).casefold()
    assert len({query.casefold() for query in queries.web_queries}) == len(
        queries.web_queries
    )


def test_academic_query_focuses_on_topic_for_scholarly_providers():
    engine = IntentEngine()
    claim = engine.reconstruct(
        engine.analyze("ada penelitian akademik tentang perkembangan ilmu hadis?")
    )
    queries = QueryGenerator().generate(claim)

    assert any("development of hadith studies" in item for item in queries.english_queries)
    assert all("research research" not in item for item in queries.english_queries)


def test_named_collection_remains_a_hypothesis_and_does_not_lock_retrieval():
    text = "Kayaknya dari Bukhari, tapi ada hadis tentang kematian?"
    engine = IntentEngine()
    claim = engine.reconstruct(engine.analyze(text))
    queries = QueryGenerator().generate(claim)

    assert claim.domain == Domain.HADITH
    assert claim.user_attribution_hypothesis == "Sahih al-Bukhari"
    assert queries.attribution_neutral_queries
    assert all(
        "bukhari" not in query.casefold()
        for query in (
            queries.attribution_neutral_queries
            + queries.indonesian_queries
            + queries.english_queries
            + queries.concept_queries
            + queries.arabic_queries
        )
    )
    assert "bukhari" in queries.attribution_signal_queries[-1].casefold()


def test_existing_general_and_unknown_domains_are_preserved():
    engine = IntentEngine()

    assert (
        engine.analyze("jelaskan perbedaan fikih dan akidah").domain_candidate
        == Domain.GENERAL_ISLAMIC
    )
    assert (
        engine.analyze("bagaimana memperbaiki koneksi Wi-Fi?").domain_candidate
        == Domain.UNKNOWN
    )
    unrelated_history = engine.analyze("bagaimana sejarah komputer berkembang?")
    assert unrelated_history.domain_candidate == Domain.UNKNOWN
    assert unrelated_history.routing_confidence < 0.50


def test_openai_client_is_never_constructed_even_when_legacy_flags_are_set(
    monkeypatch: pytest.MonkeyPatch,
):
    from sanad_core import intent as intent_module
    from sanad_core import query_generator as query_module

    for module in (intent_module, query_module):
        monkeypatch.setattr(module.settings, "sanad_enable_remote_semantic", True)
        monkeypatch.setattr(module.settings, "openai_api_key", "must-not-be-used")
        monkeypatch.setattr(module.settings, "openai_model", "must-not-be-used")

    assert IntentEngine()._client is None
    assert QueryGenerator()._client is None
