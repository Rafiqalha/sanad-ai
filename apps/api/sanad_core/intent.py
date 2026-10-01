from __future__ import annotations

import re
from .attribution import extract_user_attribution_hypothesis
from .concept_expansion import ConceptExpansionEngine
from .config import settings  # legacy configuration surface; never used for OpenAI
from .quran_reference import detect_exact_reference
from .semantic_router import LocalSemanticRouter, normalized_concepts
from .schemas import Domain, IntentAnalysis, ReconstructedClaim


INTENT_SYSTEM = """
You are the Intent Preservation Engine for SANAD.AI.

Your task is NOT to answer Islam, issue a ruling, or determine religious truth.
Your job is to preserve the user's intended request for source retrieval.

Rules:
1. Separate what the user explicitly said from what you infer.
2. Do not broaden the question to halal/haram, law, theology, or another topic unless
   the user explicitly asks it.
3. If the wording could reasonably mean materially different things, mark it ambiguous.
4. Identify the most likely retrieval domain: HADITH, QURAN,
   ISLAMIC_HISTORY, ACADEMIC_ISLAMIC_STUDIES, GENERAL_ISLAMIC, or UNKNOWN.
5. "not_explicitly_asked" should list tempting but unjustified expansions that the
   downstream system must avoid.
6. Do not provide a religious answer.
""".strip()


CLAIM_SYSTEM = """
You reconstruct a source-search claim for SANAD.AI.

Do NOT answer the religious question.
Do NOT invent a quotation.
Convert the preserved user intent into a concise searchable proposition.
If a specific attribution is explicit (e.g. Prophet Muhammad, Qur'an, Bukhari),
preserve a named collection/source only as user_attribution_hypothesis, never as
a verified attribution. Otherwise do not invent an attribution.
""".strip()


class IntentEngine:
    def __init__(self):
        self._router = LocalSemanticRouter()
        self._concept_expander = ConceptExpansionEngine()
        # Retained as a compatibility attribute for callers/tests that used to
        # disable the optional remote path. SANAD.AI v2 is local-only and never
        # constructs or calls an OpenAI client.
        self._client = None

    def analyze(self, text: str) -> IntentAnalysis:
        return self._heuristic_analyze(text)

    def reconstruct(self, intent: IntentAnalysis) -> ReconstructedClaim:
        normalized_original = " ".join(intent.original_text.split())
        low = normalized_original.casefold()
        positive_attribution_patterns = (
            r"\bsabda\s+rasulullah\b",
            r"\bnabi\s+muhammad\s+bersabda\b",
            r"\bmenurut\s+rasulullah\b",
            r"\bmenurut\s+nabi\s+muhammad\b",
        )
        negated_attribution = re.search(
            r"\b(?:bukan|tidak)\b[^.?!]{0,40}"
            r"\b(?:sabda\s+rasulullah|rasulullah|nabi\s+muhammad)\b",
            low,
        )
        explicit_prophetic_attribution = bool(
            not negated_attribution
            and any(re.search(pattern, low) for pattern in positive_attribution_patterns)
        )

        concepts = set(normalized_concepts(normalized_original))
        reconstructed = normalized_original
        if (
            intent.domain_candidate == Domain.HADITH
            and "niat" in concepts
            and concepts.intersection(
                {"amal", "berawal", "tergantung", "dimulai", "hal", "sesuatu"}
            )
        ):
            reconstructed = (
                "Mencari hadis atau dalil yang menyatakan bahwa amal/perbuatan "
                "berkaitan dengan niat."
            )
        elif intent.domain_candidate == Domain.QURAN:
            reference = detect_exact_reference(normalized_original)
            if reference and reference.verse_key:
                reconstructed = (
                    "Pengguna meminta sumber Al-Qur'an pada rujukan "
                    f"{reference.verse_key}."
                )
            elif reference and reference.chapter_name:
                reconstructed = (
                    "Pengguna meminta ayat Al-Qur'an dari surah "
                    f"{reference.chapter_name}, ayat {reference.verse_number}."
                )
            else:
                focus = re.sub(
                    r"\b(?:tolong|carikan|cari|ayat|al[-\s]?qur(?:['’]?an)?|qur(?:['’]?an)?|yang\s+menjelaskan|tentang)\b",
                    " ",
                    normalized_original,
                    flags=re.IGNORECASE,
                )
                focus = " ".join(focus.strip(" ?.,;:").split())
                if focus:
                    reconstructed = (
                        "Pengguna mencari ayat Al-Qur'an mengenai " f"{focus}."
                    )
        return ReconstructedClaim(
            reconstructed_claim=reconstructed,
            source_text=normalized_original,
            attribution_target=(
                "Prophet Muhammad" if explicit_prophetic_attribution else None
            ),
            user_attribution_hypothesis=(
                extract_user_attribution_hypothesis(normalized_original)
            ),
            search_focus=intent.key_concepts,
            domain=intent.domain_candidate,
        )

    def _heuristic_analyze(self, text: str) -> IntentAnalysis:
        low = text.casefold()
        vague_terms = ("yang itu", "dalil tentang", "apa ya")
        route = self._router.route(text)
        domain = route.domain

        words = [w for w in re.findall(r"\b[\w'-]+\b", low) if len(w) > 2]
        ambiguity_boilerplate = {
            "ada",
            "apa",
            "apakah",
            "dalil",
            "dari",
            "hadis",
            "hadith",
            "hadisnya",
            "ini",
            "itu",
            "mana",
            "sumber",
            "sumbernya",
            "tentang",
            "yang",
        }
        # Search concepts stay strictly user-derived and preserve their original
        # order. We do not translate or semantically expand them offline.
        key_concepts = list(dict.fromkeys(words))
        ambiguity_concepts = [
            word for word in key_concepts if word not in ambiguity_boilerplate
        ]
        ambiguity = 0.15
        if route.materially_ambiguous:
            ambiguity = 0.85
        elif domain in {Domain.HADITH, Domain.QURAN} and (
            len(ambiguity_concepts) < 1
            or (any(v in low for v in vague_terms) and len(ambiguity_concepts) < 4)
        ):
            ambiguity = 0.7

        semantic_concepts = set(normalized_concepts(text))
        if domain == Domain.HADITH and "niat" in semantic_concepts and semantic_concepts.intersection(
            {"amal", "berawal", "tergantung", "dimulai", "hal", "sesuatu"}
        ):
            primary = (
                "Pengguna mencari sumber mengenai hubungan amal/perbuatan "
                "dengan niat."
            )
        elif domain == Domain.HADITH:
            primary = (
                "Menelusuri sumber hadis sesuai teks dan maksud eksplisit pengguna: "
                f"{' '.join(text.split())}"
            )
        elif domain == Domain.QURAN:
            primary = (
                "Menelusuri sumber Al-Qur'an sesuai teks dan maksud eksplisit pengguna: "
                f"{' '.join(text.split())}"
            )
        elif domain == Domain.ISLAMIC_HISTORY:
            primary = (
                "Menelusuri sumber sejarah Islam sesuai tokoh, peristiwa, dan "
                f"maksud eksplisit pengguna: {' '.join(text.split())}"
            )
        elif domain == Domain.ACADEMIC_ISLAMIC_STUDIES:
            primary = (
                "Menelusuri karya akademik bidang studi Islam sesuai topik dan "
                f"maksud eksplisit pengguna: {' '.join(text.split())}"
            )
        elif domain == Domain.GENERAL_ISLAMIC:
            primary = (
                "Menentukan jenis sumber keislaman yang dimaksud tanpa memilih "
                f"hadis atau Al-Qur'an secara paksa: {' '.join(text.split())}"
            )
        else:
            primary = (
                "Pertanyaan berada di luar cakupan penelusuran sumber Islam atau "
                "belum memiliki sinyal domain yang cukup: "
                f"{' '.join(text.split())}"
            )

        clarification = route.clarification_question
        if ambiguity > 0.60 and not clarification:
            clarification = (
                "Maksud sumber yang ingin Anda telusuri masih ambigu. "
                "Bisa sebutkan potongan makna, tokoh/sumber, atau topik yang Anda ingat?"
            )

        return IntentAnalysis(
            original_text=text,
            primary_intent=primary,
            explicit_claims=[text],
            inferred_claims=[],
            not_explicitly_asked=[
                "Menentukan hukum halal atau haram",
                "Memberikan fatwa",
                "Mengembangkan pertanyaan ke isu keagamaan lain yang tidak ditanyakan",
            ],
            entities=self._extract_entities(text),
            key_concepts=key_concepts,
            domain_candidate=domain,
            routing_method=route.method,
            routing_confidence=route.confidence,
            domain_scores=route.scores,
            ambiguity_score=ambiguity,
            needs_clarification=ambiguity > 0.60,
            clarification_question=clarification if ambiguity > 0.60 else None,
        )

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """Extract explicit title-cased names without resolving their identity."""

        candidates = re.findall(
            r"(?<![\w-])(?:[A-ZÀ-ÖØ-Þ][\w'’.-]*"
            r"(?:\s+(?:[A-ZÀ-ÖØ-Þ][\w'’.-]*|al-[A-ZÀ-ÖØ-Þ][\w'’.-]*)){0,4})",
            text,
        )
        boilerplate = {
            "Ada",
            "Apakah",
            "Bagaimana",
            "Carikan",
            "Siapa",
            "Tolong",
        }
        return list(
            dict.fromkeys(
                value.strip(" ?.,;:")
                for value in candidates
                if value.strip(" ?.,;:") not in boilerplate
            )
        )
