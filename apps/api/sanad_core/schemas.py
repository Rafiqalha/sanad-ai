from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, model_validator


class Domain(str, Enum):
    QURAN = "QURAN"
    HADITH = "HADITH"
    ISLAMIC_HISTORY = "ISLAMIC_HISTORY"
    ACADEMIC_ISLAMIC_STUDIES = "ACADEMIC_ISLAMIC_STUDIES"
    GENERAL_ISLAMIC = "GENERAL_ISLAMIC"
    # Legacy discovery values remain part of the public schema for backwards
    # compatibility. New intent routing uses the two explicit domains above.
    ACADEMIC = "ACADEMIC"
    INSTITUTIONAL = "INSTITUTIONAL"
    GENERAL_DISCOVERY = "GENERAL_DISCOVERY"
    UNKNOWN = "UNKNOWN"


class LinkState(str, Enum):
    VERIFIED_DIRECT = "VERIFIED_DIRECT"
    VERIFIED_PROVIDER = "VERIFIED_PROVIDER"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    BROKEN = "BROKEN"
    UNVERIFIED = "UNVERIFIED"


class SourceClass(str, Enum):
    """Provenance category, never a score of religious truth."""

    OFFICIAL_GOVERNMENT = "OFFICIAL_GOVERNMENT"
    PRIMARY_RELIGIOUS_SOURCE = "PRIMARY_RELIGIOUS_SOURCE"
    ACADEMIC = "ACADEMIC"
    ENCYCLOPEDIC = "ENCYCLOPEDIC"
    INSTITUTIONAL = "INSTITUTIONAL"
    PUBLISHER = "PUBLISHER"
    GENERAL_WEB = "GENERAL_WEB"
    COMMUNITY = "COMMUNITY"
    UNKNOWN = "UNKNOWN"


class CacheState(str, Enum):
    HIT = "HIT"
    MISS = "MISS"
    PARTIAL = "PARTIAL"
    NOT_USED = "NOT_USED"


class EvidenceRelation(str, Enum):
    DIRECT_MATCH = "DIRECT_MATCH"
    STRONG_RELATED_MATCH = "STRONG_RELATED_MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    ATTRIBUTION_MISMATCH = "ATTRIBUTION_MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class FinalStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NO_RELIABLE_SOURCE_FOUND = "NO_RELIABLE_SOURCE_FOUND"
    PARTIAL_PROVIDER_FAILURE = "PARTIAL_PROVIDER_FAILURE"
    SOURCE_FOUND_LINK_UNVERIFIED = "SOURCE_FOUND_LINK_UNVERIFIED"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class RoutingMethod(str, Enum):
    RULE_BASED = "RULE_BASED"
    LOCAL_SEMANTIC = "LOCAL_SEMANTIC"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class RetrievalMode(str, Enum):
    EXACT_REFERENCE = "EXACT_REFERENCE"
    SEMANTIC_SEARCH = "SEMANTIC_SEARCH"
    DISCOVERY_FALLBACK = "DISCOVERY_FALLBACK"


class IntentAnalysis(BaseModel):
    original_text: str
    primary_intent: str
    explicit_claims: list[str] = Field(default_factory=list)
    inferred_claims: list[str] = Field(default_factory=list)
    not_explicitly_asked: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list)
    domain_candidate: Domain = Domain.UNKNOWN
    routing_method: RoutingMethod = RoutingMethod.RULE_BASED
    routing_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    domain_scores: dict[str, float] = Field(default_factory=dict)
    ambiguity_score: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool
    clarification_question: str | None = None


class ReconstructedClaim(BaseModel):
    reconstructed_claim: str
    source_text: str | None = None
    attribution_target: str | None = None
    user_attribution_hypothesis: str | None = None
    search_focus: list[str] = Field(default_factory=list)
    domain: Domain


class QueryBundle(BaseModel):
    indonesian_queries: list[str] = Field(default_factory=list)
    english_queries: list[str] = Field(default_factory=list)
    concept_queries: list[str] = Field(default_factory=list)
    arabic_queries: list[str] = Field(default_factory=list)
    attribution_neutral_queries: list[str] = Field(default_factory=list)
    attribution_signal_queries: list[str] = Field(default_factory=list)
    # Broad web discovery is deliberately separate from structured-provider
    # queries so legacy provider routing and evidence boundaries stay intact.
    web_queries: list[str] = Field(default_factory=list)

    @property
    def all_queries(self) -> list[str]:
        seen = set()
        out: list[str] = []
        ordered_groups = (
            self.attribution_neutral_queries,
            self.indonesian_queries,
            self.english_queries,
            self.concept_queries,
            self.arabic_queries,
            self.attribution_signal_queries,
        )
        for group in ordered_groups:
            for q in group:
                q = q.strip()
                if q and q.casefold() not in seen:
                    seen.add(q.casefold())
                    out.append(q)
        return out


class Candidate(BaseModel):
    candidate_id: str
    provider_id: str
    provider_name: str
    source_type: str
    trust_tier: int = 4

    title: str | None = None
    collection: str | None = None
    chapter: str | None = None
    item_number: str | None = None
    language: str | None = None
    retrieved_text: str | None = None
    retrieved_texts: dict[str, str] = Field(default_factory=dict)

    surah_name: str | None = None
    surah_number: int | None = None
    verse_number: int | None = None
    verse_key: str | None = None
    translation_name: str | None = None
    retrieval_mode: RetrievalMode | None = None

    source_url: str
    resolved_url: str | None = None
    source_domain: str | None = None
    page_title: str | None = None
    source_class: SourceClass | None = None
    retrieved_at: datetime | None = None
    source_identifier: str | None = None
    retrieval_queries: list[str] = Field(default_factory=list)
    metadata_complete: bool = False

    # A successful response from a registered non-Tier-1 structured provider.
    # This is deliberately distinct from Sunnah.com official API validation.
    provider_api_validated: bool = False
    # Tier-1 providers outside the Sunnah.com-specific hadith path use this
    # separate flag so HadithAPI can never be promoted through a generic field.
    canonical_provider_validated: bool = False
    official_api_validated: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class RankingFeatures(BaseModel):
    lexical_overlap: float = 0.0
    semantic_similarity: float = 0.0
    attribution_match: float = 0.0
    metadata_match: float = 0.0
    multi_query_agreement: float = 0.0
    reference_match: float = 0.0
    relevance_score: float = 0.0


class LinkValidation(BaseModel):
    state: LinkState
    original_url: str
    final_url: str | None = None
    http_status: int | None = None
    provider_domain_match: bool = False
    source_url: str | None = None
    link_state: LinkState | None = None
    link_provider: str | None = None
    link_validated_at: datetime | None = None
    exact_identity_match: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _populate_public_link_fields(self):
        # Keep the original v0 fields for compatibility while exposing the
        # explicit SourceLinkResolver contract requested by the API/UI.
        self.source_url = self.source_url or self.final_url or self.original_url
        self.link_state = self.link_state or self.state
        if self.state in {
            LinkState.VERIFIED_DIRECT,
            LinkState.VERIFIED_PROVIDER,
            LinkState.BROKEN,
        }:
            self.link_validated_at = self.link_validated_at or datetime.now(timezone.utc)
        return self


class EvidenceItem(BaseModel):
    candidate: Candidate
    ranking: RankingFeatures
    link: LinkValidation
    relationship: EvidenceRelation
    limitations: list[str] = Field(default_factory=list)


class WebSourceResult(BaseModel):
    """A public provenance record used by web and knowledge providers.

    The original web-discovery fields remain required for backwards
    compatibility.  Optional bibliographic fields let Wikipedia, OpenAlex and
    Crossref use the same presentation contract without pretending their
    metadata is primary religious evidence.
    """

    source_url: str
    resolved_url: str
    source_domain: str
    page_title: str
    source_class: SourceClass = SourceClass.UNKNOWN
    provider: str | None = None
    canonical_url: str | None = None
    publisher: str | None = None
    institution: str | None = None
    author: str | None = None
    journal: str | None = None
    year: int | None = None
    doi: str | None = None
    language: str | None = None
    open_access: bool | None = None
    oa_status: str | None = None
    authority_scope: str | None = None
    publication_date: str | None = None
    snippet: str | None = None
    content_excerpt: str | None = None
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_state: LinkState = LinkState.DISCOVERY_ONLY
    link_state: LinkState = LinkState.DISCOVERY_ONLY
    link_provider: str = "brave_web_discovery"
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    link_validated_at: datetime | None = None
    http_status: int | None = None
    retrieval_queries: list[str] = Field(default_factory=list)


class RetrievalTelemetry(BaseModel):
    structured_candidate_count: int = 0
    web_candidate_count: int = 0
    fetched_page_count: int = 0
    brave_request_count: int = 0
    brave_request_limit: int = 0
    search_cache_hits: int = 0
    search_cache_misses: int = 0
    page_cache_hits: int = 0
    page_cache_misses: int = 0
    cache_state: CacheState = CacheState.NOT_USED


class FinalResponse(BaseModel):
    raw_user_input: str | None = None
    understood_intent: str
    reconstructed_claim: str | None = None
    domain: Domain
    evidence: list[EvidenceItem] = Field(default_factory=list)
    limited_clarification: str | None = None
    expert_review_note: str | None = None
    status: FinalStatus
    generated_queries: list[str] = Field(default_factory=list)
    generated_structured_queries: list[str] = Field(default_factory=list)
    generated_web_queries: list[str] = Field(default_factory=list)
    web_results: list[WebSourceResult] = Field(default_factory=list)
    retrieval_telemetry: RetrievalTelemetry = Field(
        default_factory=RetrievalTelemetry
    )
    retrieval_mode: RetrievalMode | None = None
    routing_method: RoutingMethod | None = None
    routing_confidence: float | None = None
    user_attribution_hypothesis: str | None = None
    response_time_ms: float | None = None
    provider_errors: list[str] = Field(default_factory=list)
