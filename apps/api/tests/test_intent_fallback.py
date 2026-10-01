import re

import pytest

from sanad_core.intent import IntentEngine
from sanad_core.orchestrator import SanadOrchestrator
from sanad_core.query_generator import QueryGenerator
from sanad_core.schemas import Domain, FinalStatus


QUERY = (
    "Katanya kalau orang mencari ilmu dimudahkan jalan menuju surga, "
    "hadisnya dari mana?"
)


def _offline_components():
    intent_engine = IntentEngine()
    intent_engine._client = None
    query_generator = QueryGenerator()
    query_generator._client = None
    return intent_engine, query_generator


def test_offline_fallback_preserves_required_indonesian_claim():
    engine, _ = _offline_components()

    intent = engine.analyze(QUERY)
    claim = engine.reconstruct(intent)

    assert intent.original_text == QUERY
    assert intent.explicit_claims == [QUERY]
    assert intent.domain_candidate == Domain.HADITH
    assert intent.needs_clarification is False
    assert claim.reconstructed_claim == QUERY
    assert claim.attribution_target is None

    required = ["mencari", "ilmu", "dimudahkan", "jalan", "menuju", "surga"]
    positions = [intent.key_concepts.index(term) for term in required]
    assert positions == sorted(positions)

    user_tokens = set(re.findall(r"\b[\w'-]+\b", QUERY.casefold()))
    assert set(intent.key_concepts) <= user_tokens


def test_offline_query_generation_keeps_decisive_tail_terms():
    engine, query_generator = _offline_components()
    claim = engine.reconstruct(engine.analyze(QUERY))

    bundle = query_generator.generate(claim)

    assert any(
        all(term in query.casefold() for term in ("ilmu", "jalan", "surga"))
        for query in bundle.all_queries
    )
    assert len(bundle.indonesian_queries) >= 2
    assert 1 <= len(bundle.english_queries) <= 2
    assert bundle.concept_queries
    assert bundle.arabic_queries
    assert all(any("\u0600" <= char <= "\u06ff" for char in query) for query in bundle.arabic_queries)
    english = " ".join(bundle.english_queries).casefold()
    for untranslated in ("orang", "mencari", "ilmu", "dimudahkan", "jalan", "menuju", "surga"):
        assert untranslated not in english
    assert "حديث" in " ".join(bundle.arabic_queries)
    combined = " ".join(bundle.all_queries).casefold()
    for invented in ("bukhari", "muslim", "2699", "sunnah.com", "https://"):
        assert invented not in combined


def test_hadith_domain_does_not_imply_prophetic_attribution():
    engine, _ = _offline_components()
    claim = engine.reconstruct(
        engine.analyze("Ada hadis tentang menjaga amanah, sumbernya apa?")
    )
    assert claim.domain == Domain.HADITH
    assert claim.attribution_target is None


def test_explicit_prophetic_attribution_is_preserved_conservatively():
    engine, _ = _offline_components()
    claim = engine.reconstruct(
        engine.analyze("Di mana sumber sabda Rasulullah tentang menjaga amanah?")
    )
    assert claim.attribution_target == "Prophet Muhammad"


def test_negated_prophetic_attribution_is_not_reversed():
    engine, _ = _offline_components()
    claim = engine.reconstruct(
        engine.analyze("Ini bukan sabda Rasulullah, sumbernya apa?")
    )
    assert claim.attribution_target is None


def test_fallback_is_not_hardcoded_to_knowledge_query():
    engine, query_generator = _offline_components()
    text = "Ada hadis tentang menjaga amanah dalam perdagangan, sumbernya apa?"
    claim = engine.reconstruct(engine.analyze(text))
    bundle = query_generator.generate(claim)

    combined = " ".join(bundle.all_queries).casefold()
    assert "amanah" in combined
    assert "perdagangan" in combined
    for unrelated in ("ilmu", "jalan", "surga"):
        assert unrelated not in combined


@pytest.mark.parametrize(
    "text",
    [
        "Ada dalil tentang jalan itu?",
        "Hadis tentang hati apa ya?",
        "Hadisnya dari mana?",
        "Hadis ini sumbernya dari mana?",
    ],
)
def test_materially_ambiguous_fallback_queries_stop(text):
    engine, _ = _offline_components()
    intent = engine.analyze(text)
    assert intent.needs_clarification is True
    assert intent.ambiguity_score > 0.60


def test_specific_near_exact_hadith_query_does_not_stop():
    engine, _ = _offline_components()
    intent = engine.analyze("Ada hadis tentang amal tergantung niat?")
    assert intent.domain_candidate == Domain.HADITH
    assert intent.needs_clarification is False


@pytest.mark.parametrize(
    "text",
    [
        QUERY,
        "Ada hadis tentang amal tergantung niat?",
        "Hadis yang bilang agama itu nasihat apa sumbernya?",
        "Ada hadis bahwa Allah melihat hati dan amal, bukan penampilan?",
        "Hadis yang ada kata dunia penjara orang mukmin itu apa ya?",
        "Yang tentang orang kuat bukan yang menang bergulat itu hadis mana?",
    ],
)
def test_hadith_claims_generate_safe_multilingual_provider_queries(text):
    engine, query_generator = _offline_components()
    claim = engine.reconstruct(engine.analyze(text))
    bundle = query_generator.generate(claim)

    assert claim.domain == Domain.HADITH
    assert len(bundle.indonesian_queries) >= 2
    assert 1 <= len(bundle.english_queries) <= 2
    assert bundle.arabic_queries
    assert bundle.concept_queries
    assert all(any("\u0600" <= char <= "\u06ff" for char in query) for query in bundle.arabic_queries)


def test_semantic_hadith_paraphrase_routes_without_explicit_hadith_keyword():
    engine, _ = _offline_components()
    text = (
        "Kalau orang berjalan untuk mencari ilmu katanya dipermudah ke surga, "
        "sumbernya apa?"
    )

    intent = engine.analyze(text)

    assert intent.domain_candidate == Domain.HADITH
    assert intent.needs_clarification is False


def test_nonreligious_hearsay_does_not_route_to_hadith():
    engine, _ = _offline_components()
    intent = engine.analyze(
        "Katanya berjalan kaki memudahkan tidur, sumber penelitiannya apa?"
    )
    assert intent.domain_candidate == Domain.UNKNOWN


def test_explicit_quran_route_wins_without_explicit_hadith_wording():
    engine, _ = _offline_components()
    intent = engine.analyze("Ayat Al-Qur'an tentang mencari ilmu ada di mana?")
    assert intent.domain_candidate == Domain.QURAN


def test_named_source_is_hypothesis_and_general_queries_run_first():
    engine, query_generator = _offline_components()
    text = (
        "Katanya hadis tentang dunia sebagai penjara orang mukmin berasal dari "
        "Sahih Bukhari. Sumbernya sebenarnya dari mana?"
    )
    claim = engine.reconstruct(engine.analyze(text))
    bundle = query_generator.generate(claim)

    assert claim.user_attribution_hypothesis == "Sahih al-Bukhari"
    assert claim.attribution_target is None
    assert bundle.attribution_neutral_queries
    general_queries = (
        bundle.attribution_neutral_queries
        + bundle.indonesian_queries
        + bundle.english_queries
        + bundle.concept_queries
        + bundle.arabic_queries
    )
    assert all("bukhari" not in query.casefold() for query in general_queries)
    assert bundle.attribution_signal_queries
    assert "bukhari" in bundle.attribution_signal_queries[-1].casefold()
    assert bundle.all_queries[-1] == bundle.attribution_signal_queries[-1]


def test_quran_attribution_is_preserved_only_as_user_hypothesis():
    engine, query_generator = _offline_components()
    text = (
        "Ada yang bilang ungkapan agama itu nasihat berasal dari Al-Qur'an. "
        "Kalau sebenarnya hadis, sumbernya dari mana?"
    )
    claim = engine.reconstruct(engine.analyze(text))
    bundle = query_generator.generate(claim)

    assert claim.domain == Domain.HADITH
    assert claim.user_attribution_hypothesis == "Al-Qur'an"
    assert "qur" not in bundle.all_queries[0].casefold()
    assert "qur" in bundle.all_queries[-1].casefold()


def test_negated_named_source_does_not_become_positive_hypothesis():
    engine, query_generator = _offline_components()
    text = "Ini bukan dari Bukhari, saya hanya ingin mencari sumber hadisnya."
    claim = engine.reconstruct(engine.analyze(text))
    bundle = query_generator.generate(claim)

    assert claim.user_attribution_hypothesis is None
    assert bundle.attribution_signal_queries == []


@pytest.mark.parametrize(
    "text",
    [
        "Rakyat membutuhkan akses pendidikan.",
        "Tuliskan riwayat hidup tokoh tersebut.",
    ],
)
def test_domain_router_avoids_substring_false_positives(text):
    engine, _ = _offline_components()
    assert engine.analyze(text).domain_candidate == Domain.UNKNOWN


class _RetrievalMustNotRun:
    async def retrieve(self, queries):
        raise AssertionError("Retrieval must stop for a materially ambiguous input.")


@pytest.mark.asyncio
async def test_real_fallback_ambiguity_stops_before_retrieval():
    engine, query_generator = _offline_components()
    orchestrator = SanadOrchestrator(
        intent_engine=engine,
        query_generator=query_generator,
        retrieval=_RetrievalMustNotRun(),
    )
    response = await orchestrator.search("Hadisnya dari mana?")
    assert response.status == FinalStatus.NEEDS_CLARIFICATION
    assert response.evidence == []
