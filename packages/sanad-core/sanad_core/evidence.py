from __future__ import annotations

from .schemas import (
    Candidate,
    EvidenceItem,
    EvidenceRelation,
    LinkState,
    LinkValidation,
    RankingFeatures,
)
from .providers.sunnah import parse_sunnah_reference
from .link_validator import parse_quran_direct_reference
from .source_registry import REGISTRY


def _exact_link_identity_matches(
    candidate: Candidate,
    link: LinkValidation,
) -> bool:
    final_url = link.final_url or link.original_url
    if candidate.provider_id == "sunnah":
        if not candidate.collection or not candidate.item_number:
            return False
        expected = (
            candidate.collection.strip().casefold(),
            candidate.item_number.strip(),
        )
        return bool(
            link.original_url == candidate.source_url
            and link.http_status == 200
            and parse_sunnah_reference(link.original_url) == expected
            and parse_sunnah_reference(final_url) == expected
            and candidate.source_identifier == f"{expected[0]}:{expected[1]}"
        )
    if candidate.provider_id == "quran_foundation":
        expected_key = candidate.verse_key
        return bool(
            expected_key
            and link.original_url == candidate.source_url
            and link.http_status == 200
            and parse_quran_direct_reference(link.original_url) == expected_key
            and (
                parse_quran_direct_reference(final_url) == expected_key
                or link.exact_identity_match
            )
            and candidate.source_identifier == f"quran:{expected_key}"
        )
    return False


def eligible_for_primary_evidence(
    candidate: Candidate,
    link: LinkValidation,
) -> bool:
    registration = REGISTRY.get(candidate.provider_id)
    provider_validation = (
        candidate.official_api_validated
        if candidate.provider_id == "sunnah"
        else candidate.canonical_provider_validated
        if candidate.provider_id == "quran_foundation"
        else False
    )
    return bool(
        registration
        and registration.evidence_role == "PRIMARY_CURATED"
        and registration.trust_tier == 1
        and candidate.trust_tier == registration.trust_tier
        and candidate.metadata_complete
        and candidate.source_identifier
        and provider_validation
        and link.state == LinkState.VERIFIED_DIRECT
        and link.provider_domain_match
        and _exact_link_identity_matches(candidate, link)
    )


def classify_relation(
    candidate: Candidate,
    ranking: RankingFeatures,
    link: LinkValidation,
) -> EvidenceRelation:
    score = ranking.relevance_score

    if eligible_for_primary_evidence(candidate, link):
        if ranking.reference_match == 1.0:
            return EvidenceRelation.DIRECT_MATCH
        if score >= 0.82:
            return EvidenceRelation.DIRECT_MATCH
        if score >= 0.65:
            return EvidenceRelation.STRONG_RELATED_MATCH
        if score >= 0.45:
            return EvidenceRelation.PARTIAL_MATCH

    if score >= 0.55:
        return EvidenceRelation.PARTIAL_MATCH

    return EvidenceRelation.INSUFFICIENT_EVIDENCE


def build_evidence(
    candidate: Candidate,
    ranking: RankingFeatures,
    link: LinkValidation,
) -> EvidenceItem:
    limitations = []
    registration = REGISTRY.get(candidate.provider_id)
    if registration is None:
        limitations.append("Provider is not registered for evidence use.")
    elif registration.evidence_role != "PRIMARY_CURATED":
        limitations.append("Provider is not eligible for primary evidence.")
    if not candidate.metadata_complete:
        limitations.append("Required source metadata is incomplete.")
    if not candidate.source_identifier:
        limitations.append("A canonical source identifier is not established.")
    if link.state == LinkState.DISCOVERY_ONLY:
        limitations.append(
            "This item is discovery-only and has not been promoted to primary evidence."
        )
    elif link.state == LinkState.VERIFIED_PROVIDER:
        limitations.append("The provider is reachable, but the exact item link is unverified.")
    elif link.state == LinkState.BROKEN:
        limitations.append("The candidate link is inaccessible.")
    elif link.state == LinkState.UNVERIFIED:
        limitations.append("The candidate link has not passed validation.")
    if candidate.provider_id == "hadithapi" and candidate.provider_api_validated:
        limitations.append(
            "Metadata was returned by a curated secondary provider, not the "
            "Sunnah.com Official API."
        )
        limitations.append(
            "No provider-documented canonical direct-item URL is available."
        )
    elif candidate.source_type.startswith("hadith") and not candidate.official_api_validated:
        limitations.append("Official hadith API validation is not established.")
    if candidate.provider_id == "quran_foundation" and "id" not in candidate.retrieved_texts:
        limitations.append(
            "Terjemahan Bahasa Indonesia resmi provider tidak tersedia; tidak ada "
            "terjemahan buatan sistem yang ditampilkan."
        )
    if ranking.semantic_similarity < 0.5 and ranking.reference_match < 1.0:
        limitations.append("Semantic/relevance support is weak.")

    return EvidenceItem(
        candidate=candidate,
        ranking=ranking,
        link=link,
        relationship=classify_relation(candidate, ranking, link),
        limitations=limitations,
    )
