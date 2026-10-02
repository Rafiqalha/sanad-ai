# SANAD.AI — Internal Schemas v1.0

## 1. UserRequest

```json
{
  "request_id": "uuid",
  "input_type": "text",
  "text": "string",
  "language_hint": "id",
  "session_id": "optional"
}
```

## 2. IntentAnalysis

```json
{
  "original_text": "string",
  "primary_intent": "string",
  "explicit_claims": ["string"],
  "inferred_claims": ["string"],
  "not_explicitly_asked": ["string"],
  "entities": [],
  "key_concepts": [],
  "domain_candidate": "HADITH",
  "routing_method": "LOCAL_SEMANTIC",
  "routing_confidence": 0.86,
  "ambiguity_score": 0.18,
  "needs_clarification": false,
  "clarification_question": null
}
```

## 3. ReconstructedClaim

```json
{
  "claim_id": "C001",
  "reconstructed_claim": "string",
  "attribution_target": "Prophet Muhammad",
  "search_focus": ["knowledge", "path", "Paradise"],
  "domain": "HADITH"
}
```

## 4. SearchQuery

```json
{
  "query_id": "Q001",
  "language": "id",
  "query_text": "hadis mencari ilmu jalan menuju surga",
  "query_type": "semantic",
  "generated_from_claim_id": "C001"
}
```

## 5. Candidate

```json
{
  "candidate_id": "string",
  "provider_id": "sunnah",
  "provider_name": "Sunnah.com",
  "source_type": "hadith",
  "trust_tier": 1,
  "title": "string",
  "collection": "string",
  "chapter": "optional",
  "item_number": "optional",
  "author_or_compiler": "optional",
  "language": "ar/en",
  "retrieved_text": "string",
  "retrieved_texts": {"en": "string", "ar": "string"},
  "source_url": "string",
  "source_identifier": "string",
  "retrieval_query_ids": ["Q001", "Q002"],
  "metadata_complete": true,
  "provider_api_validated": false,
  "canonical_provider_validated": false,
  "official_api_validated": true
}
```

Qur'an candidates additionally carry `surah_name`, `surah_number`,
`verse_number`, `verse_key`, `translation_name`, and `retrieval_mode`.

`provider_api_validated` records a successful structured response from a
registered provider such as HadithAPI. It does not imply Tier-1 authority.
`official_api_validated` is reserved for the Sunnah.com Official API path.
`canonical_provider_validated` records coherent identity from another registered
canonical provider such as Quran Foundation without weakening the Sunnah-specific
boundary. A HadithAPI candidate must keep both Tier-1 flags false and can receive
`VERIFIED_PROVIDER` at most.

## 6. ValidationResult

```json
{
  "candidate_id": "string",
  "provider_registered": true,
  "domain_valid": true,
  "metadata_consistent": true,
  "link_state": "VERIFIED_DIRECT",
  "source_url": "string",
  "link_provider": "quran_foundation",
  "link_validated_at": "ISO-8601 timestamp",
  "final_url": "string",
  "eligible_as_primary_evidence": true,
  "validation_notes": []
}
```

## 7. RankingFeatures

```json
{
  "semantic_similarity": 0.93,
  "lexical_overlap": 0.74,
  "attribution_match": 1.0,
  "metadata_match": 0.90,
  "multi_query_agreement": 0.80,
  "relevance_score": 0.86
}
```

## 8. EvidenceItem

```json
{
  "candidate_id": "string",
  "relationship": "STRONG_RELATED_MATCH",
  "provider": "Sunnah.com",
  "source_label": "string",
  "excerpt": "string",
  "direct_url": "string",
  "link_state": "VERIFIED_DIRECT",
  "relevance_score": 0.86,
  "limitations": []
}
```

## 9. FinalResponse

```json
{
  "request_id": "uuid",
  "understood_intent": "string",
  "reconstructed_claim": "string",
  "domain": "HADITH",
  "evidence": [],
  "limited_clarification": "string or null",
  "expert_review_note": "string or null",
  "status": "SUCCESS"
}
```

The response also exposes generated queries, retrieval mode
(`EXACT_REFERENCE`, `SEMANTIC_SEARCH`, or `DISCOVERY_FALLBACK`), routing metadata,
unverified user attribution hypothesis, provider errors, response time,
`generated_structured_queries`, `generated_web_queries`, `web_results`, and
`retrieval_telemetry`.

Each fetched `web_results` item exposes the requested and resolved URL, domain,
page title, publisher/institution/author/date when available, bounded content
excerpt, provenance class, `DISCOVERY_ONLY` evidence state, link state/provider,
retrieval and validation timestamps, HTTP status, relevance, and the discovery
queries that led to it. No full page body or Brave credential is serialized.

Possible status values:
- SUCCESS;
- NEEDS_CLARIFICATION;
- NO_RELIABLE_SOURCE_FOUND;
- PARTIAL_PROVIDER_FAILURE;
- SOURCE_FOUND_LINK_UNVERIFIED;
- SYSTEM_ERROR.
