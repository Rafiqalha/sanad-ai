from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRegistration:
    provider_id: str
    name: str
    domains: tuple[str, ...]
    trust_tier: int
    evidence_role: str


REGISTRY = {
    "quran_foundation": SourceRegistration(
        provider_id="quran_foundation",
        name="Quran Foundation",
        domains=(
            "quran.com",
            "www.quran.com",
            "apis.quran.foundation",
            "apis-prelive.quran.foundation",
        ),
        trust_tier=1,
        evidence_role="PRIMARY_CURATED",
    ),
    "sunnah": SourceRegistration(
        provider_id="sunnah",
        name="Sunnah.com Official API",
        domains=("sunnah.com", "www.sunnah.com", "beta.sunnah.com", "api.sunnah.com"),
        trust_tier=1,
        evidence_role="PRIMARY_CURATED",
    ),
    "brave": SourceRegistration(
        provider_id="brave",
        name="Brave Search",
        domains=("api.search.brave.com",),
        trust_tier=4,
        evidence_role="DISCOVERY_ONLY",
    ),
    "hadithapi": SourceRegistration(
        provider_id="hadithapi",
        name="HadithAPI",
        domains=("hadithapi.com", "www.hadithapi.com"),
        trust_tier=2,
        evidence_role="CURATED_SECONDARY",
    ),
}
