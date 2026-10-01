from __future__ import annotations

import re

from .attribution import (
    contains_named_source_attribution,
    remove_user_attribution_hypothesis,
)
from .concept_expansion import ConceptExpansionEngine, expand_concepts
from .config import settings  # legacy configuration surface; never used for OpenAI
from .quran_reference import detect_exact_reference
from .schemas import Domain, QueryBundle, ReconstructedClaim


QUERY_SYSTEM = """
You generate retrieval queries for SANAD.AI.

Do NOT answer the religious question and do NOT authenticate any quotation.
Generate search queries only.

For a HADITH claim, create:
- 2 concise Indonesian searches;
- 1 or 2 concise English semantic searches;
- 1 concept-based search;
- up to 2 Arabic concept/phrase searches if you can do so without pretending
  the generated Arabic is an authenticated quotation.

The queries should preserve the reconstructed claim and avoid unrelated issues.
Named sources supplied by the user are unverified attribution hypotheses. Generate
general attribution-neutral queries first and place source-constrained queries last.
""".strip()


_CONCEPT_STOPWORDS = {
    "ada",
    "apa",
    "apakah",
    "asalnya",
    "bahwa",
    "benar",
    "benarkah",
    "berasal",
    "bilang",
    "dari",
    "hadis",
    "hadith",
    "hadisnya",
    "ini",
    "itu",
    "kalau",
    "katanya",
    "kata",
    "mana",
    "sebenarnya",
    "sebagai",
    "sumber",
    "sumbernya",
    "tentang",
    "ungkapan",
    "untuk",
    "yang",
    "ya",
    "aku",
    "carikan",
    "cari",
    "jelaskan",
    "menjelaskan",
    "surat",
    "surah",
    "ayat",
    "quran",
    "alquran",
}

_ENGLISH_CONCEPTS = {
    "agama": "religion",
    "allah": "Allah",
    "amal": "deeds",
    "amanah": "trust",
    "bergulat": "wrestling",
    "bukan": "not",
    "berjalan": "walking a path",
    "dipermudah": "made easy",
    "dimudahkan": "made easy",
    "dunia": "world",
    "dan": "and",
    "hati": "hearts",
    "ilmu": "knowledge",
    "jalan": "path",
    "kuat": "strong",
    "melihat": "looks at",
    "mencari": "seeking",
    "menang": "winning",
    "menjaga": "keeping",
    "menuju": "toward",
    "mukmin": "believer",
    "nasihat": "advice",
    "niat": "intentions",
    "orang": "person",
    "penampilan": "appearance",
    "penjara": "prison",
    "perdagangan": "trade",
    "surga": "paradise",
    "seseorang": "person",
    "menempuh": "travelling a path",
    "tergantung": "depend on",
    "berawal": "begin with",
    "dimulai": "begin with",
    "membebani": "burden",
    "kemampuan": "capacity",
    "kesulitan": "hardship",
    "kemudahan": "ease",
    "berbakti": "kindness",
    "orangtua": "parents",
    "tua": "parents",
    "sabar": "patience",
    "syukur": "gratitude",
    "ampun": "forgiveness",
    "ampunan": "forgiveness",
    "rezeki": "provision",
    "penciptaan": "creation",
    "langit": "heavens",
    "bumi": "earth",
    "adil": "justice",
    "keadilan": "justice",
    "cahaya": "light",
    "prasangka": "suspicion",
    "akhlak": "character",
    "akhlaknya": "character",
    "baik": "good",
    "terbaik": "best",
    "senyum": "smile",
    "tersenyum": "smile",
    "sedekah": "charity",
    "menahan": "restraining",
    "marah": "anger",
    "kemarahan": "anger",
    "berkata": "saying",
    "mengatakan": "saying",
    "hujan": "rain",
    "menghidupkan": "revives",
    "mati": "dead",
    "bangsa": "nations",
    "berbangsa": "nations",
    "suku": "tribes",
    "utang": "debt",
    "hutang": "debt",
    "mencatat": "recording",
    "catat": "recording",
    "kiblat": "prayer direction",
    "larangan": "prohibition",
    "kepada": "to",
    "dicintai": "loved",
    "lemah": "weak",
    "kematian": "death",
    "orang_tua": "parents",
    "perkembangan": "development",
    "berkembang": "development",
    "berkembangnya": "development",
    "tetangga": "neighbor",
    "gangguan": "harm",
    "mengganggu": "harming",
    "perang": "battle",
    "hadis": "hadith",
    "quran": "Quran",
}

_ARABIC_CONCEPTS = {
    "agama": "الدين",
    "allah": "الله",
    "amal": "الأعمال",
    "amanah": "الأمانة",
    "bergulat": "المصارعة",
    "bukan": "ليس",
    "berjalan": "سلوك طريق",
    "dipermudah": "يسهل",
    "dimudahkan": "يسهل",
    "dunia": "الدنيا",
    "dan": "و",
    "hati": "القلوب",
    "ilmu": "العلم",
    "jalan": "الطريق",
    "kuat": "القوي",
    "melihat": "ينظر",
    "mencari": "طلب",
    "menang": "الغلبة",
    "menjaga": "حفظ",
    "menuju": "إلى",
    "mukmin": "المؤمن",
    "nasihat": "النصيحة",
    "niat": "النيات",
    "orang": "الشخص",
    "penampilan": "الصور",
    "penjara": "سجن",
    "perdagangan": "التجارة",
    "seseorang": "شخص",
    "surga": "الجنة",
    "tergantung": "بحسب",
    "berawal": "تبدأ",
    "dimulai": "تبدأ",
    "membebani": "يكلف",
    "kemampuan": "وسعها",
    "kesulitan": "العسر",
    "kemudahan": "اليسر",
    "berbakti": "الإحسان",
    "orangtua": "الوالدين",
    "tua": "الوالدين",
    "sabar": "الصبر",
    "syukur": "الشكر",
    "ampun": "المغفرة",
    "ampunan": "المغفرة",
    "rezeki": "الرزق",
    "penciptaan": "خلق",
    "langit": "السماوات",
    "bumi": "الأرض",
    "adil": "العدل",
    "keadilan": "العدل",
    "cahaya": "النور",
    "prasangka": "الظن",
    "akhlak": "الأخلاق",
    "akhlaknya": "الأخلاق",
    "baik": "حسن",
    "terbaik": "خير",
    "senyum": "التبسم",
    "tersenyum": "التبسم",
    "sedekah": "صدقة",
    "menahan": "يمسك",
    "marah": "الغضب",
    "kemarahan": "الغضب",
    "berkata": "القول",
    "mengatakan": "القول",
    "hujan": "المطر",
    "menghidupkan": "يحيي",
    "mati": "ميتة",
    "bangsa": "شعوبا",
    "berbangsa": "شعوبا",
    "suku": "قبائل",
    "utang": "الدين",
    "hutang": "الدين",
    "mencatat": "الكتابة",
    "catat": "الكتابة",
    "kiblat": "القبلة",
    "larangan": "النهي",
    "kepada": "إلى",
    "dicintai": "أحب",
    "lemah": "الضعيف",
    "tetangga": "الجار",
    "gangguan": "الأذى",
    "mengganggu": "إيذاء",
}


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = " ".join(value.split()).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            out.append(normalized)
    return out


def _content_concepts(text: str) -> list[str]:
    expansion = expand_concepts(text)
    return [
        token
        for token in expansion.core_terms
        if len(token) > 2 and token not in _CONCEPT_STOPWORDS
    ]


_OPEN_TOPIC_STOPWORDS = (
    _CONCEPT_STOPWORDS
    - {"hadis", "hadith", "quran", "alquran"}
    | {
        "akademik",
        "bagaimana",
        "biografi",
        "ilmiah",
        "kajian",
        "penelitian",
        "research",
        "riset",
        "sejarah",
        "siapa",
        "studi",
    }
)


def _open_topic_concepts(text: str) -> list[str]:
    """Keep the researched topic while removing retrieval boilerplate."""

    expansion = expand_concepts(text)
    return [
        token
        for token in expansion.core_terms
        if len(token) > 2 and token not in _OPEN_TOPIC_STOPWORDS
    ]


def _open_english_topic(concepts: list[str]) -> str:
    """Create a local semantic topic phrase, never a work/source identity."""

    remaining = list(concepts)
    phrases: list[str] = []
    if "ilmu" in remaining and "hadis" in remaining:
        remaining.remove("ilmu")
        remaining.remove("hadis")
        phrases.append("hadith studies")
    translated = [_ENGLISH_CONCEPTS.get(token, token) for token in remaining]
    if "development" in translated:
        translated.remove("development")
        subject = " ".join([*translated, *phrases]).strip()
        return f"development of {subject}".strip()
    return " ".join([*translated, *phrases]).strip()


def _english_concept_text(concepts: list[str]) -> str:
    expansion = expand_concepts(concepts)
    return expansion.english_phrases[0] if expansion.english_phrases else ""


def _arabic_concept_text(concepts: list[str]) -> str:
    expansion = expand_concepts(concepts)
    return expansion.arabic_phrases[0] if expansion.arabic_phrases else ""


def _english_provider_phrase(concepts: list[str]) -> str | None:
    """Build one short provider query from explicit translated concepts.

    HadithAPI's text filter is substantially narrower than a web search. This
    refinement stays inside the user's concepts and is only a retrieval query;
    it is never presented as an authenticated quotation.
    """

    translated = [_ENGLISH_CONCEPTS[c] for c in concepts if c in _ENGLISH_CONCEPTS]
    words = set(" ".join(translated).casefold().split())
    if {"path", "paradise"} <= words:
        return "path to Paradise"
    if "intentions" in words and "deeds" in words:
        # HadithAPI's text filter behaves as a phrase/sub-string filter rather
        # than a vector search. Keep this query to the most distinctive user
        # concept so wording variants can still be discovered dynamically.
        return "intentions"
    if {"mukmin", "kuat"} <= set(concepts):
        return "strong believer"
    # Use one distinctive, user-derived concept for substring-oriented APIs.
    # This is generic retrieval logic, not a phrase-to-reference answer map.
    unhelpful = {
        "Allah", "and", "not", "person", "source", "reported", "saying",
        "hadith", "good", "best", "to",
    }
    distinctive = [
        word.strip(".,;:!?()")
        for word in translated
        if word.strip(".,;:!?()") and word not in unhelpful
    ]
    return max(distinctive, key=len) if distinctive else None


def _hadith_semantic_variants(
    concepts: list[str],
    concept_text: str,
    english_text: str,
) -> tuple[list[str], list[str]]:
    """Create semantic search variants without assigning a source/reference."""

    concept_set = set(concepts)
    expansion = expand_concepts(concepts)
    expanded_indonesian = max(
        expansion.indonesian_phrases or (concept_text,),
        key=lambda value: (len(value.split()), len(value)),
    )
    expanded_english = max(
        expansion.english_phrases or (english_text,),
        key=lambda value: (len(value.split()), len(value)),
    )
    indonesian = [
        f"{expanded_indonesian} hadis",
        f"hadis tentang {concept_text}",
    ]
    english = [
        f"{expanded_english} hadith",
        f"hadith about {english_text}",
    ]
    if {"amal", "niat"} <= concept_set:
        indonesian.insert(0, "amal atau perbuatan bergantung pada niat hadis")
        english = [
            "actions are judged by intentions hadith",
            "deeds depend upon intentions hadith",
            "hadith about intention and deeds",
        ]
    elif {"ilmu", "surga"} <= concept_set:
        english.insert(0, "seeking knowledge path to paradise hadith")
    return _unique(indonesian), _unique(english)


class QueryGenerator:
    def __init__(self):
        self._concept_expander = ConceptExpansionEngine()
        # Compatibility attribute only. SANAD.AI v2 performs deterministic
        # local query generation and never constructs an OpenAI client.
        self._client = None

    def generate(self, claim: ReconstructedClaim) -> QueryBundle:
        generated = QueryBundle()

        if claim.domain == Domain.HADITH:
            return self._ensure_hadith_requirements(claim, generated)
        if claim.domain == Domain.QURAN:
            return self._ensure_quran_requirements(claim, generated)
        if claim.domain in {
            Domain.ISLAMIC_HISTORY,
            Domain.ACADEMIC_ISLAMIC_STUDIES,
        }:
            return self._ensure_open_retrieval_requirements(claim, generated)

        expansion = self._concept_expander.expand(
            claim.source_text or claim.reconstructed_claim or claim.search_focus
        )
        concepts = " ".join(expansion.core_terms).replace("_", " ").strip()
        base = claim.reconstructed_claim.strip()
        return QueryBundle(
            indonesian_queries=(
                generated.indonesian_queries or ([base, concepts] if concepts else [base])
            ),
            english_queries=_unique(
                list(expansion.english_phrases[:2]) + generated.english_queries
            )[:2],
            concept_queries=_unique(
                list(expansion.indonesian_phrases[1:3])
                + generated.concept_queries
            )[:2],
            arabic_queries=_unique(
                list(expansion.arabic_phrases[:2]) + generated.arabic_queries
            )[:2],
            attribution_neutral_queries=generated.attribution_neutral_queries,
            attribution_signal_queries=generated.attribution_signal_queries,
            web_queries=_unique(
                [concepts or base, *generated.web_queries]
            )[:2],
        )

    @staticmethod
    def _ensure_hadith_requirements(
        claim: ReconstructedClaim, generated: QueryBundle
    ) -> QueryBundle:
        base = " ".join(claim.reconstructed_claim.split()).strip()
        source_text = " ".join((claim.source_text or base).split()).strip()
        hypothesis = claim.user_attribution_hypothesis
        neutral_base = (
            remove_user_attribution_hypothesis(base) if hypothesis else base
        )
        neutral_base = neutral_base or base

        concepts = _content_concepts(neutral_base)
        if not concepts:
            concepts = [
                concept
                for concept in claim.search_focus
                if concept.casefold() not in _CONCEPT_STOPWORDS
            ]
        expansion = expand_concepts(concepts)
        concept_text = (
            expansion.indonesian_phrases[0]
            if expansion.indonesian_phrases
            else " ".join(concepts[:12]).replace("_", " ").strip()
        ) or neutral_base
        english_text = (
            _english_concept_text(concepts) or "reported saying source identification"
        )
        arabic_text = _arabic_concept_text(concepts)

        semantic_indonesian, semantic_english = _hadith_semantic_variants(
            concepts,
            concept_text,
            english_text,
        )
        indonesian = [neutral_base, *semantic_indonesian]
        english = list(semantic_english)
        provider_phrase = _english_provider_phrase(concepts)
        if provider_phrase:
            english = [semantic_english[0], provider_phrase]
        semantic_concept = max(
            expansion.indonesian_phrases or (concept_text,),
            key=lambda value: (len(value.split()), len(value)),
        )
        concept_queries = [f"hadis {concept_text}", semantic_concept]
        if arabic_text:
            semantic_arabic = max(
                expansion.arabic_phrases or (arabic_text,),
                key=lambda value: (len(value.split()), len(value)),
            )
            arabic = [f"حديث {arabic_text}", f"حديث {semantic_arabic}"]
        else:
            arabic = []
        signal_queries = (
            list(generated.attribution_signal_queries) if hypothesis else []
        )

        # Model-generated source constraints are accepted only when they repeat
        # a source hypothesis explicitly supplied by the user. General queries
        # remain first and attribution-bearing variants remain supplemental.
        for query in generated.indonesian_queries:
            if contains_named_source_attribution(query):
                if hypothesis:
                    signal_queries.append(query)
                continue
            indonesian.append(query)
        for query in generated.english_queries:
            if contains_named_source_attribution(query):
                if hypothesis:
                    signal_queries.append(query)
                continue
            english.append(query)
        for query in generated.concept_queries:
            if not contains_named_source_attribution(query):
                concept_queries.append(query)

        if hypothesis:
            signal_queries.append(source_text)

        return QueryBundle(
            indonesian_queries=_unique(indonesian)[:4],
            english_queries=_unique(english)[:2],
            concept_queries=_unique(concept_queries)[:2],
            arabic_queries=_unique(
                arabic
                + [
                    query
                    for query in generated.arabic_queries
                    if not contains_named_source_attribution(query)
                ]
            )[:2],
            attribution_neutral_queries=([neutral_base] if hypothesis else []),
            attribution_signal_queries=_unique(signal_queries),
            # Broad discovery is deliberately unrestricted. A trusted-source
            # constraint may be added later as a supplemental query, but is
            # never forced onto every request.
            web_queries=_unique(
                [*semantic_english[:1], *semantic_indonesian[:1]]
                + list(generated.web_queries)
            )[:2],
        )

    @staticmethod
    def _ensure_quran_requirements(
        claim: ReconstructedClaim, generated: QueryBundle
    ) -> QueryBundle:
        source_text = " ".join((claim.source_text or claim.reconstructed_claim).split())
        hypothesis = claim.user_attribution_hypothesis
        neutral = remove_user_attribution_hypothesis(source_text) if hypothesis else source_text
        neutral = neutral or source_text
        reference = detect_exact_reference(neutral)

        concepts = _content_concepts(neutral)
        expansion = expand_concepts(concepts)
        concept_text = (
            expansion.indonesian_phrases[0]
            if expansion.indonesian_phrases
            else " ".join(concepts[:14]).replace("_", " ").strip()
        )
        english_text = _english_concept_text(concepts)
        arabic_text = _arabic_concept_text(concepts)

        if reference:
            reference_text = reference.verse_key or (
                f"{reference.chapter_name} {reference.verse_number}"
            )
            indonesian = [
                f"rujukan Al-Qur'an {reference_text}",
                neutral,
            ]
        else:
            # These remain content queries. No entry maps a phrase to a verse.
            # The Quran Search API must discover every verse key dynamically.
            indonesian = [
                concept_text or neutral,
                f"makna Al-Qur'an mengenai {concept_text or neutral}",
            ]

        signal_queries = list(generated.attribution_signal_queries) if hypothesis else []
        if hypothesis:
            signal_queries.append(source_text)

        for query in generated.indonesian_queries:
            if contains_named_source_attribution(query):
                if hypothesis:
                    signal_queries.append(query)
            else:
                indonesian.append(query)

        english = (
            list(expansion.english_phrases[:2])
            if expansion.english_phrases
            else ([english_text] if english_text else [])
        ) + [
            query
            for query in generated.english_queries
            if not contains_named_source_attribution(query)
        ]
        arabic = (
            list(expansion.arabic_phrases[:2])
            if expansion.arabic_phrases
            else ([arabic_text] if arabic_text else [])
        ) + [
            query
            for query in generated.arabic_queries
            if not contains_named_source_attribution(query)
        ]

        return QueryBundle(
            indonesian_queries=_unique(indonesian)[:3],
            english_queries=_unique(english)[:2],
            concept_queries=_unique(
                [concept_text]
                + list(expansion.indonesian_phrases[1:3])
                + list(generated.concept_queries)
                if concept_text
                else list(generated.concept_queries)
            )[:2],
            arabic_queries=_unique(arabic)[:2],
            attribution_neutral_queries=([neutral] if hypothesis else []),
            attribution_signal_queries=_unique(signal_queries),
            web_queries=_unique(
                ([f"Quran verse about {english_text}"] if english_text else [])
                + [f"ayat Al-Qur'an tentang {concept_text or neutral}"]
                + list(generated.web_queries)
            )[:2],
        )

    @staticmethod
    def _ensure_open_retrieval_requirements(
        claim: ReconstructedClaim, generated: QueryBundle
    ) -> QueryBundle:
        """Build broad, multilingual queries for history and scholarship.

        Unlike structured scripture retrieval, these domains intentionally
        produce open-web/metadata searches. No provider, work, person identity,
        DOI, or historical conclusion is guessed here.
        """

        source_text = " ".join(
            (claim.source_text or claim.reconstructed_claim).split()
        ).strip()
        hypothesis = claim.user_attribution_hypothesis
        neutral = (
            remove_user_attribution_hypothesis(source_text)
            if hypothesis
            else source_text
        )
        neutral = neutral or source_text
        topic_concepts = _open_topic_concepts(neutral)
        expansion = expand_concepts(topic_concepts or neutral)
        concept_text = (
            expansion.indonesian_phrases[0]
            if expansion.indonesian_phrases
            else " ".join(claim.search_focus).strip()
        ) or neutral
        english_text = _open_english_topic(topic_concepts) or (
            expansion.english_phrases[0]
            if expansion.english_phrases
            else concept_text
        )

        if claim.domain == Domain.ISLAMIC_HISTORY:
            indonesian = [neutral, f"sejarah Islam {concept_text}"]
            english = [
                f"Islamic history {english_text}",
                f"{english_text} historical sources biography",
            ]
            arabic = [
                f"تاريخ إسلامي {phrase}"
                for phrase in expansion.arabic_phrases[:2]
            ]
            web_queries = [indonesian[1], english[0]]
        else:
            indonesian = [
                neutral,
                f"penelitian akademik studi Islam {concept_text}",
            ]
            english = [
                f"Islamic studies {english_text}",
                f"scholarly research on {english_text}",
            ]
            arabic = [
                f"دراسات إسلامية أكاديمية {phrase}"
                for phrase in expansion.arabic_phrases[:2]
            ]
            web_queries = [indonesian[1], english[0]]

        signal_queries = (
            list(generated.attribution_signal_queries) if hypothesis else []
        )
        if hypothesis:
            signal_queries.append(source_text)

        for query in generated.indonesian_queries:
            if contains_named_source_attribution(query):
                if hypothesis:
                    signal_queries.append(query)
            else:
                indonesian.append(query)
        english.extend(
            query
            for query in generated.english_queries
            if not contains_named_source_attribution(query)
        )
        arabic.extend(
            query
            for query in generated.arabic_queries
            if not contains_named_source_attribution(query)
        )

        return QueryBundle(
            indonesian_queries=_unique(indonesian)[:3],
            english_queries=_unique(english)[:2],
            concept_queries=_unique(
                list(expansion.indonesian_phrases[1:3])
                + list(generated.concept_queries)
            )[:2],
            # Arabic is included only when the local lexicon has sufficiently
            # confident concept vocabulary. Names are never transliterated by
            # guesswork.
            arabic_queries=_unique(arabic)[:2],
            attribution_neutral_queries=([neutral] if hypothesis else []),
            attribution_signal_queries=_unique(signal_queries),
            web_queries=_unique(web_queries + list(generated.web_queries))[:2],
        )
