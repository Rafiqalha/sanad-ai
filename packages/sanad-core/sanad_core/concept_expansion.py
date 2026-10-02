from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Sequence


_TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]+(?:[-'’][\w\u0600-\u06ff]+)*", re.UNICODE)


@dataclass(frozen=True)
class ConceptFamily:
    """A multilingual lexical family used only to broaden retrieval.

    A family deliberately contains no verse number, hadith number, collection,
    URL, or authenticity judgment. It describes vocabulary, not an answer.
    """

    canonical: str
    aliases: tuple[str, ...]
    indonesian: tuple[str, ...]
    english: tuple[str, ...]
    arabic: tuple[str, ...]


@dataclass(frozen=True)
class ConceptExpansion:
    original_text: str
    normalized_terms: tuple[str, ...]
    core_terms: tuple[str, ...]
    matched_concepts: tuple[str, ...]
    unknown_terms: tuple[str, ...]
    indonesian_terms: tuple[str, ...]
    english_terms: tuple[str, ...]
    arabic_terms: tuple[str, ...]
    indonesian_phrases: tuple[str, ...]
    english_phrases: tuple[str, ...]
    arabic_phrases: tuple[str, ...]

    # Friendly aliases keep the object convenient for provider/pipeline code.
    @property
    def concepts(self) -> list[str]:
        return list(self.core_terms)

    @property
    def indonesian_concepts(self) -> list[str]:
        return list(self.indonesian_terms)

    @property
    def english_concepts(self) -> list[str]:
        return list(self.english_terms)

    @property
    def arabic_concepts(self) -> list[str]:
        return list(self.arabic_terms)

    @property
    def all_terms(self) -> list[str]:
        return _unique(
            [
                *self.indonesian_terms,
                *self.english_terms,
                *self.arabic_terms,
            ]
        )

    def phrases(self, language: str) -> list[str]:
        key = language.casefold().replace("-", "_")
        if key in {"id", "indonesian", "bahasa_indonesia"}:
            return list(self.indonesian_phrases)
        if key in {"en", "english"}:
            return list(self.english_phrases)
        if key in {"ar", "arabic"}:
            return list(self.arabic_phrases)
        raise ValueError(f"Unsupported concept language: {language}")


_FAMILIES: tuple[ConceptFamily, ...] = (
    ConceptFamily(
        canonical="niat",
        aliases=(
            "niat",
            "niatnya",
            "berniat",
            "kesengajaan",
            "intent",
            "intention",
            "intentions",
            "النية",
            "النيات",
        ),
        indonesian=("niat", "tujuan perbuatan", "keikhlasan niat"),
        english=("intention", "intentions and deeds", "sincere intention"),
        arabic=("النية", "النيات والأعمال", "إخلاص النية"),
    ),
    ConceptFamily(
        canonical="sabar",
        aliases=(
            "sabar",
            "kesabaran",
            "bersabar",
            "tabah",
            "patience",
            "patient",
            "steadfastness",
            "الصبر",
        ),
        indonesian=("sabar", "kesabaran", "ketabahan", "teguh menghadapi ujian"),
        english=("patience", "steadfastness", "perseverance in hardship"),
        arabic=("الصبر", "الثبات", "الصبر على البلاء"),
    ),
    ConceptFamily(
        canonical="rezeki",
        aliases=(
            "rezeki",
            "rejeki",
            "nafkah",
            "penghidupan",
            "provision",
            "sustenance",
            "livelihood",
            "الرزق",
        ),
        indonesian=("rezeki", "penghidupan", "kelapangan rezeki"),
        english=("provision", "sustenance", "livelihood"),
        arabic=("الرزق", "سعة الرزق", "المعيشة"),
    ),
    ConceptFamily(
        canonical="ilmu",
        aliases=(
            "ilmu",
            "pengetahuan",
            "belajar",
            "pembelajaran",
            "knowledge",
            "learning",
            "seeking knowledge",
            "العلم",
            "طلب العلم",
        ),
        indonesian=("ilmu", "mencari ilmu", "belajar dan pengetahuan"),
        english=("knowledge", "seeking knowledge", "learning"),
        arabic=("العلم", "طلب العلم", "التعلم"),
    ),
    ConceptFamily(
        canonical="marah",
        aliases=(
            "marah",
            "kemarahan",
            "amarah",
            "anger",
            "rage",
            "الغضب",
        ),
        indonesian=("marah", "menahan marah", "mengendalikan kemarahan"),
        english=("anger", "restraining anger", "self-control when angry"),
        arabic=("الغضب", "كظم الغيظ", "ضبط الغضب"),
    ),
    ConceptFamily(
        canonical="orang_tua",
        aliases=(
            "orang tua",
            "orangtua",
            "kedua orang tua",
            "ibu bapak",
            "ayah ibu",
            "parents",
            "parent",
            "filial piety",
            "الوالدين",
            "بر الوالدين",
        ),
        indonesian=("orang tua", "berbakti kepada orang tua", "ibu dan ayah"),
        english=("parents", "kindness to parents", "filial piety"),
        arabic=("الوالدين", "بر الوالدين", "الإحسان إلى الوالدين"),
    ),
    ConceptFamily(
        canonical="kematian",
        aliases=(
            "kematian",
            "mati",
            "wafat",
            "meninggal",
            "ajal",
            "death",
            "dying",
            "remembrance of death",
            "الموت",
            "ذكر الموت",
            "الأجل",
        ),
        indonesian=("kematian", "mengingat kematian", "ajal", "kubur"),
        english=("death", "remember death", "remembrance of death", "appointed time", "grave"),
        arabic=("الموت", "ذكر الموت", "الأجل", "القبر"),
    ),
    ConceptFamily(
        canonical="sedekah",
        aliases=(
            "sedekah",
            "bersedekah",
            "shadaqah",
            "sadaqah",
            "charity",
            "almsgiving",
            "الصدقة",
            "صدقة",
        ),
        indonesian=("sedekah", "bersedekah", "amal sedekah"),
        english=("charity", "almsgiving", "voluntary charity"),
        arabic=("الصدقة", "صدقة التطوع", "الإنفاق"),
    ),
    ConceptFamily(
        canonical="akhlak",
        aliases=(
            "akhlak",
            "akhlaknya",
            "budi pekerti",
            "karakter",
            "moral",
            "morals",
            "character",
            "good character",
            "الأخلاق",
            "حسن الخلق",
        ),
        indonesian=("akhlak", "akhlak mulia", "budi pekerti", "karakter yang baik"),
        english=("character", "good character", "moral conduct"),
        arabic=("الأخلاق", "حسن الخلق", "مكارم الأخلاق"),
    ),
    ConceptFamily(
        canonical="tetangga",
        aliases=(
            "tetangga",
            "bertetangga",
            "neighbor",
            "neighbors",
            "neighbour",
            "neighbours",
            "الجار",
            "الجيران",
        ),
        indonesian=("tetangga", "hak tetangga", "tidak mengganggu tetangga"),
        english=("neighbor", "rights of neighbors", "not harming a neighbor"),
        arabic=("الجار", "حق الجار", "كف الأذى عن الجار"),
    ),
)


# General lexical normalization supports both the router and unseen queries.
# Entries are vocabulary translations only; they never identify scripture.
_TOKEN_ALIASES: dict[str, str] = {
    "actions": "amal",
    "action": "amal",
    "deeds": "amal",
    "deed": "amal",
    "amalan": "amal",
    "perbuatan": "amal",
    "perbuatannya": "amal",
    "amalnya": "amal",
    "knowledge": "ilmu",
    "learn": "ilmu",
    "learning": "ilmu",
    "seeking": "mencari",
    "seek": "mencari",
    "pathway": "jalan",
    "path": "jalan",
    "heaven": "surga",
    "paradise": "surga",
    "verse": "ayat",
    "verses": "ayat",
    "chapter": "surah",
    "quranic": "quran",
    "qur'an": "quran",
    "alquran": "quran",
    "القرآن": "quran",
    "آية": "ayat",
    "حديث": "hadis",
    "الأعمال": "amal",
    "karakter": "akhlak",
    "tersenyum": "senyum",
    "senyuman": "senyum",
    "orangtua": "orang_tua",
    "parents": "orang_tua",
    "parent": "orang_tua",
    "nations": "bangsa",
    "nation": "bangsa",
    "tribes": "suku",
    "rain": "hujan",
    "revives": "menghidupkan",
    "debt": "utang",
    "history": "sejarah",
    "historical": "sejarah",
    "hadith": "hadis",
    "development": "perkembangan",
    "developments": "perkembangan",
    "battle": "perang",
    "war": "perang",
    "dynasty": "dinasti",
    "caliphate": "kekhalifahan",
    "research": "penelitian",
    "scholarly": "akademik",
    "academic": "akademik",
    "studies": "studi",
    "journal": "jurnal",
}

_PHRASE_ALIASES: dict[tuple[str, ...], str] = {}
for _family in _FAMILIES:
    for _alias in _family.aliases:
        _parts = tuple(_TOKEN_RE.findall(_alias.casefold()))
        if _parts:
            _PHRASE_ALIASES[_parts] = _family.canonical
            if len(_parts) == 1:
                _TOKEN_ALIASES[_parts[0]] = _family.canonical


_TRANSLATIONS: dict[str, tuple[str, str]] = {
    "agama": ("religion", "الدين"),
    "allah": ("Allah", "الله"),
    "amal": ("deeds", "الأعمال"),
    "amanah": ("trust", "الأمانة"),
    "ayat": ("verse", "آية"),
    "bergulat": ("wrestling", "المصارعة"),
    "berjalan": ("walking a path", "سلوك طريق"),
    "berbakti": ("kindness", "الإحسان"),
    "bumi": ("earth", "الأرض"),
    "cahaya": ("light", "النور"),
    "dimudahkan": ("made easy", "يسهل"),
    "dipermudah": ("made easy", "يسهل"),
    "dunia": ("world", "الدنيا"),
    "hati": ("hearts", "القلوب"),
    "hujan": ("rain", "المطر"),
    "ilmu": ("knowledge", "العلم"),
    "jalan": ("path", "الطريق"),
    "keadilan": ("justice", "العدل"),
    "kemampuan": ("capacity", "الوسع"),
    "kematian": ("death", "الموت"),
    "kemudahan": ("ease", "اليسر"),
    "kesulitan": ("hardship", "العسر"),
    "kiblat": ("prayer direction", "القبلة"),
    "kuat": ("strong", "القوي"),
    "langit": ("heavens", "السماوات"),
    "larangan": ("prohibition", "النهي"),
    "marah": ("anger", "الغضب"),
    "mencari": ("seeking", "طلب"),
    "menghidupkan": ("revives", "يحيي"),
    "menahan": ("restraining", "كظم"),
    "menempuh": ("travelling a path", "سلوك طريق"),
    "menuju": ("toward", "إلى"),
    "mukmin": ("believer", "المؤمن"),
    "nasihat": ("advice", "النصيحة"),
    "niat": ("intentions", "النية"),
    "orang": ("person", "شخص"),
    "orang_tua": ("parents", "الوالدين"),
    "penciptaan": ("creation", "الخلق"),
    "perdagangan": ("trade", "التجارة"),
    "penampilan": ("appearance", "الصور"),
    "penjara": ("prison", "السجن"),
    "prasangka": ("suspicion", "الظن"),
    "quran": ("Quran", "القرآن"),
    "rezeki": ("provision", "الرزق"),
    "sabar": ("patience", "الصبر"),
    "sedekah": ("charity", "الصدقة"),
    "senyum": ("smile", "التبسم"),
    "surga": ("paradise", "الجنة"),
    "syukur": ("gratitude", "الشكر"),
    "utang": ("debt", "الدين المالي"),
    "akhlak": ("character", "الأخلاق"),
    "sejarah": ("history", "التاريخ"),
    "perang": ("battle", "معركة"),
    "dinasti": ("dynasty", "سلالة"),
    "kekhalifahan": ("caliphate", "الخلافة"),
    "perkembangan": ("development", "تطور"),
    "penelitian": ("research", "بحث"),
    "akademik": ("academic", "أكاديمي"),
    "studi": ("studies", "دراسات"),
    "jurnal": ("journal", "مجلة علمية"),
    "manuskrip": ("manuscript", "مخطوط"),
    "hadis": ("hadith", "الحديث"),
    "tetangga": ("neighbor", "الجار"),
    "gangguan": ("harm", "الأذى"),
    "mengganggu": ("harming", "إيذاء"),
}


_STOPWORDS = {
    "ada",
    "aku",
    "apa",
    "apakah",
    "bagaimana",
    "bahwa",
    "benar",
    "benarkah",
    "bisa",
    "carikan",
    "cari",
    "dalil",
    "dalam",
    "dari",
    "dan",
    "dengan",
    "di",
    "gak",
    "ini",
    "itu",
    "jelaskan",
    "kalau",
    "kata",
    "katanya",
    "ke",
    "mana",
    "mengenai",
    "menjelaskan",
    "menyatakan",
    "oleh",
    "pada",
    "kepada",
    "saya",
    "sebuah",
    "soal",
    "sabda",
    "sumber",
    "sumbernya",
    "tentang",
    "tolong",
    "untuk",
    "yang",
    "siapa",
    "ya",
    "about",
    "find",
    "source",
    "the",
    "what",
}


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = " ".join(str(value).replace("_", " ").split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _canonical_token(token: str) -> str:
    token = token.casefold().strip("_'’-")
    direct = _TOKEN_ALIASES.get(token)
    if direct:
        return direct

    # Indonesian enclitics are safe to peel only when the resulting vocabulary
    # is known. Unknown terms remain intact, so novel user concepts are never
    # silently rewritten into a guessed root.
    for suffix in ("nya", "lah", "kah", "pun"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            candidate = token[: -len(suffix)]
            if candidate in _TOKEN_ALIASES or candidate in _TRANSLATIONS:
                return _TOKEN_ALIASES.get(candidate, candidate)
    return token


class ConceptExpansionEngine:
    """Deterministic multilingual concept expansion for retrieval.

    The engine is intentionally local and answer-agnostic. Known vocabulary is
    expanded semantically; previously unseen terms are retained and combined
    into dynamic search phrases instead of being dropped or mapped to a fixed
    religious reference.
    """

    def normalize_tokens(self, text: str, *, keep_stopwords: bool = True) -> list[str]:
        raw = _TOKEN_RE.findall(text.casefold())
        normalized: list[str] = []
        index = 0
        max_phrase = max(len(parts) for parts in _PHRASE_ALIASES)
        while index < len(raw):
            matched: str | None = None
            consumed = 1
            for size in range(min(max_phrase, len(raw) - index), 1, -1):
                phrase = tuple(raw[index : index + size])
                if phrase in _PHRASE_ALIASES:
                    matched = _PHRASE_ALIASES[phrase]
                    consumed = size
                    break
            value = matched or _canonical_token(raw[index])
            if keep_stopwords or value not in _STOPWORDS:
                normalized.append(value)
            index += consumed
        return normalized

    def expand(self, text_or_terms: str | Sequence[str]) -> ConceptExpansion:
        if isinstance(text_or_terms, str):
            original = " ".join(text_or_terms.split())
        else:
            original = " ".join(str(term) for term in text_or_terms if str(term).strip())

        normalized = self.normalize_tokens(original, keep_stopwords=True)
        core = _unique(
            term
            for term in normalized
            if len(term) > 2 and term not in _STOPWORDS
        )
        # Convert display strings back to canonical underscore form for lookup.
        canonical_core = [term.replace(" ", "_") for term in core]

        family_by_name = {family.canonical: family for family in _FAMILIES}
        matched_names = list(
            dict.fromkeys(term for term in canonical_core if term in family_by_name)
        )
        matched_families = [family_by_name[name] for name in matched_names]

        unknown = [
            term.replace("_", " ")
            for term in canonical_core
            if term not in _TRANSLATIONS and term not in family_by_name
        ]

        base_indonesian = " ".join(term.replace("_", " ") for term in canonical_core[:14])
        translated_english = [
            _TRANSLATIONS[term][0]
            for term in canonical_core[:14]
            if term in _TRANSLATIONS
        ]
        translated_arabic = [
            _TRANSLATIONS[term][1]
            for term in canonical_core[:14]
            if term in _TRANSLATIONS
        ]

        # Unknown terms are retained as search entities in one English phrase.
        # No claim is made that they were translated.
        english_search_entities = [
            term for term in unknown if re.search(r"[a-z]", term, re.IGNORECASE)
        ]
        english_base_parts = [*translated_english, *english_search_entities[:5]]
        base_english = " ".join(_unique(english_base_parts))
        base_arabic = " ".join(_unique(translated_arabic))

        indonesian_terms = _unique(
            [
                *(term.replace("_", " ") for term in canonical_core),
                *(value for family in matched_families for value in family.indonesian),
            ]
        )
        english_terms = _unique(
            [
                *translated_english,
                *(value for family in matched_families for value in family.english),
            ]
        )
        arabic_terms = _unique(
            [
                *translated_arabic,
                *(value for family in matched_families for value in family.arabic),
            ]
        )

        indonesian_phrases = _unique(
            [
                base_indonesian,
                *(value for family in matched_families for value in family.indonesian),
            ]
        )
        english_phrases = _unique(
            [
                base_english,
                *(value for family in matched_families for value in family.english),
            ]
        )
        arabic_phrases = _unique(
            [
                base_arabic,
                *(value for family in matched_families for value in family.arabic),
            ]
        )

        return ConceptExpansion(
            original_text=original,
            normalized_terms=tuple(normalized),
            core_terms=tuple(canonical_core),
            matched_concepts=tuple(matched_names),
            unknown_terms=tuple(_unique(unknown)),
            indonesian_terms=tuple(indonesian_terms),
            english_terms=tuple(english_terms),
            arabic_terms=tuple(arabic_terms),
            indonesian_phrases=tuple(indonesian_phrases),
            english_phrases=tuple(english_phrases),
            arabic_phrases=tuple(arabic_phrases),
        )


_DEFAULT_ENGINE = ConceptExpansionEngine()


def normalize_concepts(text: str) -> list[str]:
    """Backwards-compatible normalization entry point for local components."""

    return _DEFAULT_ENGINE.normalize_tokens(text, keep_stopwords=True)


def expand_concepts(text_or_terms: str | Sequence[str]) -> ConceptExpansion:
    return _DEFAULT_ENGINE.expand(text_or_terms)
