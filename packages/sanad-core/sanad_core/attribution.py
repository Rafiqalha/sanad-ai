from __future__ import annotations

import re


_SOURCE_ALIASES: tuple[tuple[str, str], ...] = (
    ("Sahih al-Bukhari", r"(?:sahih\s+)?(?:al[-\s]?)?bukhari"),
    ("Sahih Muslim", r"(?:sahih\s+)?muslim"),
    ("Sunan Abi Dawud", r"(?:sunan\s+)?(?:abi|abu)\s+da(?:w)?ud"),
    ("Jami at-Tirmidhi", r"(?:jami[’'`]?\s+at[-\s]?)?tirmi(?:dhi|dzi)"),
    ("Sunan an-Nasai", r"(?:sunan\s+)?(?:an[-\s]?)?nasa(?:i|’i|'i)"),
    ("Sunan Ibn Majah", r"(?:sunan\s+)?ibn\s+majah"),
    ("Riyad as-Salihin", r"riyad(?:h)?\s+(?:as[-\s]?)?sali(?:hin|heen)"),
    ("Al-Qur'an", r"(?:al[-\s]?)?qur(?:'an|’an|an)|alquran"),
)

_PREFIX = r"(?:berasal\s+dari|dinisbatkan\s+kepada|diriwayatkan\s+oleh|riwayat|menurut|dari)"


def _patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple(
        (
            canonical,
            re.compile(rf"\b{_PREFIX}\s+(?:{alias})\b", re.IGNORECASE),
        )
        for canonical, alias in _SOURCE_ALIASES
    )


_ATTRIBUTION_PATTERNS = _patterns()

_TENTATIVE_SOURCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (
        canonical,
        re.compile(
            rf"\b(?:kayaknya|mungkin|sepertinya)\s+(?:berasal\s+)?(?:dari\s+)?"
            rf"(?:{alias})\b",
            re.IGNORECASE,
        ),
    )
    for canonical, alias in _SOURCE_ALIASES
)

_TENTATIVE_SURAH_PATTERN = re.compile(
    r"\b(?:kayaknya|mungkin|sepertinya)\s+(?:berasal\s+)?(?:dari\s+)?"
    r"(?P<source>(?:(?:surat|surah)\s+)?al[-\s][a-z][a-z'’\-]*)\b",
    re.IGNORECASE,
)


def extract_user_attribution_hypothesis(text: str) -> str | None:
    """Return a named-source attribution stated by the user, never a verified fact."""

    for canonical, pattern in _ATTRIBUTION_PATTERNS:
        for match in pattern.finditer(text):
            preceding = text[max(0, match.start() - 24) : match.start()]
            if re.search(r"\b(?:bukan|tidak)\s*$", preceding, re.IGNORECASE):
                continue
            return canonical
    for canonical, pattern in _TENTATIVE_SOURCE_PATTERNS:
        if pattern.search(text):
            return canonical
    tentative_surah = _TENTATIVE_SURAH_PATTERN.search(text)
    if tentative_surah:
        source = " ".join(tentative_surah.group("source").split())
        return f"Qur'an: {source}"
    return None


def remove_user_attribution_hypothesis(text: str) -> str:
    """Remove named-source attribution clauses while preserving the remaining claim."""

    cleaned = text
    for _, pattern in _ATTRIBUTION_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    for _, pattern in _TENTATIVE_SOURCE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = _TENTATIVE_SURAH_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\s+([,.;:?!])", r"\1", cleaned)
    cleaned = re.sub(r"([,.;:])(?:\s*[,.])+(?=\s|$)", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" ,;:")


def contains_named_source_attribution(text: str) -> bool:
    return extract_user_attribution_hypothesis(text) is not None
