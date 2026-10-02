from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from rapidfuzz.fuzz import ratio, token_set_ratio


_NUMERIC_REFERENCE = re.compile(
    r"(?<!\d)(?P<chapter>[1-9]|[1-9]\d|1[01]\d|11[0-4])\s*:\s*"
    r"(?P<verse>[1-9]\d{0,2})(?!\d)"
)
_SURAH_REFERENCE = re.compile(
    r"\b(?:surat|surah)\s+(?P<name>[\w'’\-\s]{2,55}?)"
    r"\s+(?:ayat\s+)?(?P<verse>[1-9]\d{0,2})\b",
    re.IGNORECASE,
)
_NAMED_AYAH_REFERENCE = re.compile(
    r"(?P<name>[\w'’\-]+(?:\s+[\w'’\-]+){0,3})\s+ayat\s+"
    r"(?P<verse>[1-9]\d{0,2})\b",
    re.IGNORECASE,
)
_BARE_AL_REFERENCE = re.compile(
    r"(?P<name>(?:al|ali|an|at|ash|ad|ar|as|az)[-\s][\w'’\-]+)\s+"
    r"(?P<verse>[1-9]\d{0,2})\b",
    re.IGNORECASE,
)
_COMMAND_PREFIX = re.compile(
    r"^(?:tolong\s+)?(?:carikan|cari|tampilkan|ambil|buka|lihat)\s+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QuranReferenceHint:
    verse_number: int
    chapter_number: int | None = None
    chapter_name: str | None = None

    @property
    def verse_key(self) -> str | None:
        if self.chapter_number is None:
            return None
        return f"{self.chapter_number}:{self.verse_number}"


def normalize_chapter_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.replace("’", "'")
    normalized = re.sub(r"\b(?:surat|surah)\b", " ", normalized)
    normalized = re.sub(r"[^\w\u0600-\u06ff]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def detect_exact_reference(text: str) -> QuranReferenceHint | None:
    numeric = _NUMERIC_REFERENCE.search(text)
    if numeric:
        return QuranReferenceHint(
            chapter_number=int(numeric.group("chapter")),
            verse_number=int(numeric.group("verse")),
        )

    match = _SURAH_REFERENCE.search(text)
    if match is None:
        match = _NAMED_AYAH_REFERENCE.search(text)
    if match is None:
        match = _BARE_AL_REFERENCE.search(text)
    if match is None:
        return None

    name = _COMMAND_PREFIX.sub("", match.group("name").strip())
    name = re.sub(r"^(?:ayat|quran|al[-\s]?quran)\s+", "", name, flags=re.I)
    name = " ".join(name.split()).strip(" ,;:-")
    if not name:
        return None
    return QuranReferenceHint(chapter_name=name, verse_number=int(match.group("verse")))


def resolve_chapter(
    hint: QuranReferenceHint,
    chapters: list[dict[str, Any]],
) -> tuple[int, str, int | None]:
    """Resolve a reference against provider-returned chapter metadata.

    The resolver contains no phrase-to-verse table. Named surahs are matched to
    the live/provider chapter list, and the returned verse count bounds the
    requested ayah when metadata is available.
    """

    usable: list[tuple[int, str, int | None, list[str]]] = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        raw_id = chapter.get("id")
        try:
            chapter_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if not 1 <= chapter_id <= 114:
            continue
        simple_name = str(chapter.get("name_simple") or "").strip()
        if not simple_name:
            continue
        count_raw = chapter.get("verses_count")
        try:
            verses_count = int(count_raw) if count_raw is not None else None
        except (TypeError, ValueError):
            verses_count = None
        translated = chapter.get("translated_name")
        translated_name = (
            str(translated.get("name") or "").strip()
            if isinstance(translated, dict)
            else ""
        )
        names = [
            simple_name,
            str(chapter.get("name_complex") or "").strip(),
            str(chapter.get("name_arabic") or "").strip(),
            translated_name,
        ]
        usable.append((chapter_id, simple_name, verses_count, [n for n in names if n]))

    if hint.chapter_number is not None:
        match = next((item for item in usable if item[0] == hint.chapter_number), None)
        if match is None:
            raise ValueError("Nomor surah tidak ditemukan pada metadata provider.")
        chapter_id, name, count, _ = match
    else:
        wanted = normalize_chapter_name(hint.chapter_name or "")
        if not wanted:
            raise ValueError("Nama surah kosong.")
        ranked: list[tuple[float, tuple[int, str, int | None, list[str]]]] = []
        for item in usable:
            aliases = [normalize_chapter_name(name) for name in item[3]]
            score = max(
                max(ratio(wanted, alias), token_set_ratio(wanted, alias))
                for alias in aliases
            )
            ranked.append((score, item))
        if not ranked:
            raise ValueError("Metadata surah dari provider kosong.")
        score, match = max(ranked, key=lambda item: item[0])
        if score < 76:
            raise ValueError("Nama surah tidak dapat dicocokkan secara meyakinkan.")
        chapter_id, name, count, _ = match

    if count is not None and hint.verse_number > count:
        raise ValueError("Nomor ayat berada di luar rentang surah provider.")
    return chapter_id, name, count
