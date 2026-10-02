# SANAD.AI — Architecture v2.0

## Component map

### A. User Interface
Responsibilities:
- collect text input;
- later accept audio/video;
- show intent summary;
- show source candidates;
- expose link-validation state;
- show limitations.

No provider secrets are stored here.

### B. API / Orchestration Layer
Recommended language:
- Python.

Recommended framework:
- FastAPI for production-oriented backend;
- a CLI or simple Python script for Phase 1A proof of concept.

Responsibilities:
- request lifecycle;
- provider concurrency;
- timeouts;
- error handling;
- structured response.

### C. Intent Layer
Modules:
- IntentAnalyzer;
- ClaimReconstructor;
- AmbiguityDetector;
- DomainClassifier.

### D. Query Layer
Modules:
- QueryGenerator;
- QueryDeduplicator;
- LanguageVariantGenerator.

### E. Source Layer
Modules:
- SourceRegistry;
- SourceRouter;
- provider adapters.

Initial adapters:
- QuranFoundationProvider;
- SunnahProvider;
- HadithAPIProvider;
- MediaWikiProvider;
- BroadWebDiscoveryProvider;
- SafePageRetriever;
- OpenAlexProvider;
- CrossrefProvider;
- WebDiscoveryProvider (optional later).

### F. Retrieval Layer
Responsibilities:
- async provider calls;
- response normalization;
- duplicate detection;
- candidate pooling.

### G. Ranking Layer
Stages:
1. lexical signals;
2. semantic similarity;
3. attribution and metadata signals;
4. second-stage reranking;
5. source-eligibility filter.

### H. Validation Layer
Modules:
- ProvenanceValidator;
- DirectLinkValidator;
- MetadataConsistencyValidator.

### I. Evidence Layer
Modules:
- EvidenceAligner;
- EvidencePackBuilder;
- LimitedClarifier.

---

## Control flow

1. POST user input
2. normalize text
3. analyze intent
4. if materially ambiguous → return clarification
5. reconstruct search claim
6. classify domain
7. generate queries
8. route by domain:
   - HADITH → HadithAPI structured retrieval; optional independent bounded
     broad-web discovery may add provenance/supporting pages without changing
     the structured evidence state; the older Sunnah-restricted Brave path
     remains a fallback when the structured provider is inadequate;
   - QURAN exact reference → Quran Foundation Content API;
   - QURAN semantic request → Search API, then Content API for each candidate;
   - ISLAMIC_HISTORY / ACADEMIC_ISLAMIC_STUDIES → Indonesian-first MediaWiki
     actual-page retrieval plus OpenAlex, Crossref DOI validation, and an optional
     bounded Brave discovery branch;
9. for broad discovery, open only the bounded top candidates and reject unsafe,
   broken, unreadable, or semantically irrelevant pages
10. classify web provenance without assigning religious correctness
11. normalize provider results
12. remove duplicates
13. validate provider provenance
14. compute relevance features
15. rerank
16. validate direct links and exact-item identity
17. align claim with evidence
18. build evidence pack
19. generate limited clarification only from retrieved evidence
20. return structured JSON plus request/cache/provider telemetry

The concept-expansion layer broadens Indonesian concepts into independent
Indonesian, English, and high-confidence Arabic retrieval vocabulary. It never
maps a concept directly to a verse, hadith number, DOI, or URL.

History/academic sources share a presentation schema but retain their evidence
boundary: Wikipedia is `ENCYCLOPEDIC`, OpenAlex/Crossref are scholarly discovery
and metadata, and fetched Brave pages remain `DISCOVERY_ONLY`.

---

## Provider adapter contract

Every provider must implement conceptually:

- `search(queries, context) -> list[Candidate]`
- `normalize(raw_result) -> Candidate`
- `validate_candidate(candidate) -> ValidationResult`
- `build_or_extract_direct_link(candidate) -> LinkResult`

Provider-specific assumptions must stay inside the adapter.

Hadith provider order for the temporary path:

1. HadithAPI structured search (`VERIFIED_PROVIDER` at most);
2. bounded broad Brave discovery + safe page retrieval (`DISCOVERY_ONLY` always);
3. legacy Sunnah-restricted Brave fallback (`DISCOVERY_ONLY`);
4. Sunnah.com Official API validation when credentials and an exact reference are available (`VERIFIED_DIRECT` only after direct-link validation).

Qur'an provider path:

1. Quran Foundation Search/Content API with backend OAuth credentials;
2. exact references are resolved against provider chapter metadata;
3. semantic verse keys must originate from Search API and are hydrated through
   Content API;
4. Quran.com direct links are derived only from a provider-returned verse key and
   become `VERIFIED_DIRECT` only after liveness and same-verse identity checks;
5. unavailable credentials or provider failure returns an honest unavailable/no
   evidence state, never a locally fabricated verse.

---

## Concurrency

Independent provider calls should run concurrently.

Recommended behavior:
- per-provider timeout;
- provider-specific retry policy;
- circuit-breaker behavior if one source repeatedly fails;
- partial success accepted.

The system must return useful evidence when one provider fails but others succeed.

---

## Statelessness

Core requests are designed to be stateless.
Optional short-lived cache may be used for:
- repeated API responses;
- access tokens;
- repeated search queries/results;
- bounded fetched-page excerpts.

The improvement tracker stores only sanitized, aggregate in-memory patterns.
Every change still requires candidate creation, tests, regression validation,
human approval, and a separate manual release. Automatic self-training and
automatic production updates are prohibited.

Audio/video support is currently interface-only and fail-closed. No transcript,
claim, or evidence is created until a real transcription engine is configured.

Cache is not an authoritative corpus.

---

## Phase 1A minimal implementation

Required modules:
- `schemas.py`
- `intent.py`
- `query_generator.py`
- `source_registry.py`
- `semantic_router.py`
- `providers/sunnah.py`
- `providers/hadithapi.py`
- `retrieval.py`
- `reranker.py`
- `source_link_resolver.py`
- `link_validator.py`
- `evidence.py`
- `main.py`

Do not build a polished frontend until the command-line or API proof of concept passes test cases.
