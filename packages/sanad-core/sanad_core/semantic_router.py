from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from math import sqrt
import re

from rapidfuzz.fuzz import token_set_ratio

from .concept_expansion import normalize_concepts
from .schemas import Domain, RoutingMethod


_PROTOTYPES = {
    Domain.HADITH: (
        "amal niat sumber riwayat",
        "ucapan sabda nabi perawi",
        "mencari ilmu jalan surga sumber",
        "reported saying narration source",
        "perkataan teladan akhlak perbuatan sumber",
        "ingatan samar ungkapan nasihat riwayat",
    ),
    Domain.QURAN: (
        "ayat surah quran rujukan",
        "firman wahyu kitab suci sumber",
        "quran verse chapter reference",
        "ayat tema makna terjemahan surah",
    ),
    Domain.ISLAMIC_HISTORY: (
        "sejarah islam tokoh peristiwa masa lalu",
        "perang dinasti kekhalifahan sultan kerajaan muslim",
        "islamic history battle dynasty caliphate biography",
        "kronologi peradaban umat islam sumber sejarah",
    ),
    Domain.ACADEMIC_ISLAMIC_STUDIES: (
        "penelitian akademik studi islam jurnal ilmiah",
        "riset ilmu hadis kajian quran sejarah islam",
        "islamic studies scholarly research journal paper",
        "publikasi penulis tahun doi bibliografi",
    ),
    Domain.GENERAL_ISLAMIC: (
        "dalil islam ibadah akidah fikih",
        "agama allah doa pahala hukum",
        "islamic religious source",
    ),
}

_HADITH_EXPLICIT = re.compile(
    r"\b(?:hadis(?:nya)?|hadith|riwayat(?!\s+hidup)|sabda|rasul(?:ullah)?|nabi)\b",
    re.IGNORECASE,
)
_QURAN_EXPLICIT = re.compile(
    r"\b(?:al[-\s]?qur(?:['’]?an)?|alquran|qur(?:['’]?an)?|surah?|ayat|firman)\b",
    re.IGNORECASE,
)
_QURAN_NUMERIC_REFERENCE = re.compile(r"(?<!\d)(?:[1-9]|[1-9]\d|1[01]\d|11[0-4])\s*:\s*\d{1,3}(?!\d)")
_MIXED_REQUEST = re.compile(
    r"\b(?:hadis|hadith|riwayat)\b[^?.!]{0,32}\b(?:atau|dan/atau)\b[^?.!]{0,32}\b(?:ayat|qur(?:['’]?an)?)\b"
    r"|\b(?:ayat|qur(?:['’]?an)?)\b[^?.!]{0,32}\b(?:atau|dan/atau)\b[^?.!]{0,32}\b(?:hadis|hadith|riwayat)\b",
    re.IGNORECASE,
)
_ISLAMIC_CONTEXT = re.compile(
    r"\b(?:allah|islam|agama|amal|niat|dalil|doa|iman|ibadah|fikih|fiqih|"
    r"pahala|dosa|surga|neraka|zakat|sedekah|salat|shalat|puasa|sabar|"
    r"syukur|taubat|mukmin|ilmu|rezeki|rejeki|kematian|ajal|kubur|"
    r"marah|akhlak|orang\s+tua)\b",
    re.IGNORECASE,
)
_SOURCE_SEEKING = re.compile(
    r"\b(?:sumber(?:nya)?|dalil|dari\s+mana|asal(?:nya)?|benar(?:kah)?|carikan|cari|telusuri|lupa|katanya)\b",
    re.IGNORECASE,
)

_ACADEMIC_SIGNAL = re.compile(
    r"\b(?:penelitian(?:\s+(?:akademik|ilmiah))?|kajian(?:\s+(?:akademik|ilmiah))?|"
    r"studi\s+akademik|riset|research|"
    r"artikel\s+ilmiah|karya\s+ilmiah|jurnal(?:\s+ilmiah)?|paper|"
    r"publikasi|scholarly|academic\s+(?:research|study|work)|doi|"
    r"openalex|crossref|bibliografi|literature\s+review|tinjauan\s+pustaka)\b",
    re.IGNORECASE,
)
_ACADEMIC_ISLAMIC_CONTEXT = re.compile(
    r"\b(?:islam|islamic|muslim|qur(?:['’]?an)?|alquran|hadis|hadith|"
    r"sunah|sunnah|fikih|fiqih|akidah|syariah|tasawuf|sirah|"
    r"ulama|ilmu\s+hadis|tafsir|peradaban\s+islam)\b",
    re.IGNORECASE,
)
_HISTORY_SIGNAL = re.compile(
    r"\b(?:sejarah|histor(?:y|ical)|kronologi|perang|battle|dinasti|dynasty|"
    r"kekhalifahan|caliphate|kesultanan|sultanate|kerajaan|empire|"
    r"peradaban|civilization|biografi|perkembangan|berkembang(?:nya)?|"
    r"masa\s+pemerintahan|era|"
    r"manuskrip|manuscript|asal[-\s]?usul)\b",
    re.IGNORECASE,
)
_ISLAMIC_HISTORY_CONTEXT = re.compile(
    r"\b(?:islam|islamic|muslim|qur(?:['’]?an)?|alquran|hadis|hadith|"
    r"nabi|rasul|muhammad|sahabat|khalifah|"
    r"khulafaur|hijrah|badar|uhud|khandaq|tabuk|abbasiyah|abbasid|"
    r"umayyah|umayyad|utsmani|ottoman|mamluk|ayyubi|andalus|"
    r"nusantara|ulama|masjid|sirah|sultan|kesultanan|kekhalifahan|"
    r"baitul\s+hikmah|baghdad|damaskus|kairo|"
    r"salib|saladin|salahuddin)\b",
    re.IGNORECASE,
)
_ISLAMIC_PERSON_QUERY = re.compile(
    r"\b(?:siapa|who\s+was|who\s+is|biografi)\b[^?.!]{0,100}"
    r"(?:\bal[-\s][\w'’.-]+|\b(?:ibn|ibnu|bin|binti)\b|"
    r"\b(?:imam|sultan|khalifah|syekh|syaikh|sheikh)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticRoute:
    domain: Domain
    method: RoutingMethod
    confidence: float
    scores: dict[str, float]
    materially_ambiguous: bool = False
    clarification_question: str | None = None


def normalized_concepts(text: str) -> list[str]:
    # Keep this established import path for provider/reranker compatibility;
    # normalization itself now belongs to the Concept Expansion Engine.
    return normalize_concepts(text)


def _char_ngram_cosine(left: str, right: str, size: int = 3) -> float:
    """Dependency-free local semantic fallback tolerant of spelling variation."""

    def vector(value: str) -> Counter[str]:
        value = f"  {' '.join(normalized_concepts(value))}  "
        return Counter(value[index : index + size] for index in range(len(value) - size + 1))

    first = vector(left)
    second = vector(right)
    if not first or not second:
        return 0.0
    dot = sum(count * second.get(key, 0) for key, count in first.items())
    left_norm = sqrt(sum(count * count for count in first.values()))
    right_norm = sqrt(sum(count * count for count in second.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _prototype_scores(text: str) -> dict[str, float]:
    normalized = " ".join(normalized_concepts(text))
    scores: dict[str, float] = {}
    for domain, prototypes in _PROTOTYPES.items():
        scores[domain.value] = max(
            max(
                token_set_ratio(normalized, prototype) / 100.0,
                (0.72 * (token_set_ratio(normalized, prototype) / 100.0))
                + (0.28 * _char_ngram_cosine(normalized, prototype)),
            )
            for prototype in prototypes
        )
    return scores


class LocalSemanticRouter:
    """Rule-first, local multilingual domain routing.

    The fallback uses only local normalization and fuzzy prototype similarity.
    It neither calls a model/API nor authenticates a religious claim.
    """

    def route(self, text: str) -> SemanticRoute:
        normalized = " ".join(text.split())
        low = normalized.casefold()
        scores = _prototype_scores(normalized)

        has_hadith = bool(_HADITH_EXPLICIT.search(low))
        has_quran = bool(_QURAN_EXPLICIT.search(low) or _QURAN_NUMERIC_REFERENCE.search(low))

        # Explicit correction/contrast determines the requested route while the
        # earlier named source remains only an attribution hypothesis.
        corrects_to_hadith = bool(
            re.search(r"\b(?:sebenarnya|tetapi|tapi)\s+(?:itu\s+)?hadis\b", low)
        )
        corrects_to_quran = bool(
            re.search(r"\b(?:sebenarnya|tetapi|tapi)\s+(?:itu\s+)?(?:ayat|qur(?:['’]?an)?)\b", low)
        )
        if corrects_to_hadith:
            return SemanticRoute(
                Domain.HADITH, RoutingMethod.RULE_BASED, 0.98, scores
            )
        if corrects_to_quran:
            return SemanticRoute(
                Domain.QURAN, RoutingMethod.RULE_BASED, 0.98, scores
            )

        # Research intent and historical intent describe different retrieval
        # corpora. They therefore take precedence over incidental words such as
        # "hadis", "ayat", or "nabi" inside the topic being researched.
        is_academic = bool(
            _ACADEMIC_SIGNAL.search(low) and _ACADEMIC_ISLAMIC_CONTEXT.search(low)
        )
        if is_academic:
            scores[Domain.ACADEMIC_ISLAMIC_STUDIES.value] = max(
                scores[Domain.ACADEMIC_ISLAMIC_STUDIES.value], 0.96
            )
            return SemanticRoute(
                Domain.ACADEMIC_ISLAMIC_STUDIES,
                RoutingMethod.RULE_BASED,
                0.96,
                scores,
            )

        is_history = bool(
            (_HISTORY_SIGNAL.search(low) and _ISLAMIC_HISTORY_CONTEXT.search(low))
            or _ISLAMIC_PERSON_QUERY.search(normalized)
        )
        if is_history:
            scores[Domain.ISLAMIC_HISTORY.value] = max(
                scores[Domain.ISLAMIC_HISTORY.value], 0.96
            )
            return SemanticRoute(
                Domain.ISLAMIC_HISTORY,
                RoutingMethod.RULE_BASED,
                0.96,
                scores,
            )

        if _MIXED_REQUEST.search(low):
            return SemanticRoute(
                domain=Domain.GENERAL_ISLAMIC,
                method=RoutingMethod.RULE_BASED,
                confidence=0.99,
                scores=scores,
                materially_ambiguous=True,
                clarification_question=(
                    "Apakah Anda ingin menelusuri sumber hadis, ayat Al-Qur'an, "
                    "atau keduanya secara terpisah?"
                ),
            )

        if has_hadith and has_quran:
            return SemanticRoute(
                domain=Domain.GENERAL_ISLAMIC,
                method=RoutingMethod.RULE_BASED,
                confidence=0.86,
                scores=scores,
                materially_ambiguous=True,
                clarification_question=(
                    "Pertanyaan menyebut hadis dan Al-Qur'an. Sumber mana yang "
                    "ingin Anda telusuri lebih dahulu?"
                ),
            )
        if has_quran:
            return SemanticRoute(
                Domain.QURAN, RoutingMethod.RULE_BASED, 0.98, scores
            )
        if has_hadith:
            return SemanticRoute(
                Domain.HADITH, RoutingMethod.RULE_BASED, 0.98, scores
            )

        concepts = set(normalized_concepts(low))
        if "niat" in concepts and concepts.intersection(
            {"amal", "berawal", "tergantung", "dimulai", "hal", "sesuatu"}
        ):
            scores[Domain.HADITH.value] = max(scores[Domain.HADITH.value], 0.86)
        if {"ilmu", "jalan", "surga"} <= concepts or {
            "ilmu",
            "mencari",
            "surga",
        } <= concepts:
            scores[Domain.HADITH.value] = max(scores[Domain.HADITH.value], 0.88)

        # A remembered aphorism/contrast presented for source tracing is a
        # hadith-like retrieval intent even when the user omitted the word
        # "hadis". This routes the search; it never authenticates the saying.
        remembered_saying = bool(
            re.search(r"\b(?:lupa|ingat|katanya|konon|samar[- ]?samar)\b", low)
        )
        contrastive_claim = bool(
            re.search(r"\bbukan\b[^.?!]{1,100}\b(?:tapi|tetapi|melainkan)\b", low)
        )
        if _SOURCE_SEEKING.search(low) and (
            contrastive_claim
            or (remembered_saying and _ISLAMIC_CONTEXT.search(low))
        ):
            scores[Domain.HADITH.value] = max(scores[Domain.HADITH.value], 0.76)

        best_domain_value, best_score = max(scores.items(), key=lambda item: item[1])
        best_domain = Domain(best_domain_value)
        runner_up = sorted(scores.values(), reverse=True)[1]

        if (
            best_domain
            in {
                Domain.HADITH,
                Domain.QURAN,
                Domain.ISLAMIC_HISTORY,
                Domain.ACADEMIC_ISLAMIC_STUDIES,
            }
            and best_score >= 0.58
            and best_score - runner_up >= 0.08
            and (
                _SOURCE_SEEKING.search(low)
                or _ISLAMIC_CONTEXT.search(low)
                or _ISLAMIC_HISTORY_CONTEXT.search(low)
                or _ACADEMIC_ISLAMIC_CONTEXT.search(low)
            )
        ):
            return SemanticRoute(
                best_domain,
                RoutingMethod.LOCAL_SEMANTIC,
                round(min(0.95, best_score), 4),
                scores,
            )

        if _ISLAMIC_CONTEXT.search(low):
            return SemanticRoute(
                domain=Domain.GENERAL_ISLAMIC,
                method=RoutingMethod.LOCAL_SEMANTIC,
                confidence=round(max(0.55, scores[Domain.GENERAL_ISLAMIC.value]), 4),
                scores=scores,
                materially_ambiguous=True,
                clarification_question=(
                    "Apakah sumber yang ingin Anda telusuri berupa hadis, ayat "
                    "Al-Qur'an, atau sumber keislaman lain?"
                ),
            )

        return SemanticRoute(
            domain=Domain.UNKNOWN,
            method=RoutingMethod.OUT_OF_SCOPE,
            # UNKNOWN is reserved for genuinely low-confidence routing. A high
            # similarity without Islamic context must not masquerade as a
            # confident classification.
            confidence=round(min(0.49, max(0.0, best_score)), 4),
            scores=scores,
        )
