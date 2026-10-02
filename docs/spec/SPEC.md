# SANAD.AI — Technical Specification v1.0 (Phase 1 Freeze)

## 1. Product definition

SANAD.AI is an AI-assisted Islamic knowledge provenance and source-retrieval system.

Its primary function is NOT to issue religious verdicts. Its core function is to:
1. understand the user's intended meaning;
2. preserve that meaning without semantic drift;
3. reconstruct the input into a searchable claim;
4. search trusted live internet sources;
5. retrieve source candidates;
6. validate provenance and direct links;
7. rank candidates by relevance;
8. present verifiable evidence and links;
9. provide only limited referential clarification when supported by retrieved evidence.

Core principle:

> Understand the intent → trace the source → show the evidence → leave substantive religious judgment to qualified scholarship.

---

## 2. Epistemic boundaries

SANAD.AI MAY:
- understand paraphrased Indonesian questions;
- distinguish explicit meaning from inferred meaning;
- ask clarification when intent is ambiguous;
- identify whether a request is likely Qur'an-related, hadith-related, academic, institutional, or general;
- generate multiple search queries;
- retrieve candidates from trusted online providers;
- compare the user's wording with retrieved evidence;
- correct referential errors such as wrong attribution, wrong verse number, or wrong collection when supported by evidence;
- provide direct source links that pass validation;
- state when evidence is insufficient.

SANAD.AI MUST NOT:
- issue fatwa;
- independently determine halal/haram;
- declare one contested interpretation as religiously final;
- generate a source from model memory;
- present a search-engine snippet as a primary source;
- turn similarity scores into a "truth score";
- expand the user's question into unrelated religious issues;
- invent citation metadata when missing.

---

## 3. Storage architecture

Version 1 is source-on-demand and semi-stateless.

SANAD.AI does NOT maintain a permanent local corpus of:
- the Qur'an;
- hadith collections;
- kitab;
- fatwas;
- academic literature.

It MAY store:
- source-provider configuration;
- provider trust tier;
- API endpoint configuration;
- temporary query/session cache;
- test fixtures;
- application logs without sensitive content;
- optional user feedback.

Any cache is performance-oriented and must not be treated as the authoritative source.

---

## 4. Initial scope

### Phase 1A — core proof of concept
Input:
- Indonesian text.

Primary target:
- paraphrased hadith request.

Expected output:
- preserved intent;
- reconstructed claim;
- detected domain;
- candidate hadith sources;
- provider;
- collection/number/title if available;
- evidence snippet;
- validated direct link or explicitly labeled discovery link;
- uncertainty/failure state.

### Phase 1B
Add:
- Qur'an route;
- academic-support route;
- broader institutional source route.

### Phase 1C
Add:
- audio transcription;
- video transcription;
- optional supporting-literature retrieval.

Out of scope for v1 core:
- deepfake detection;
- full kitab-kuning coverage;
- all fiqh schools;
- all fatwa sources;
- automatic religious verdict;
- complex Digital Sanad Map;
- automatic theological truth classification.

---

## 5. Acceptance criteria for the core

The core is considered technically alive only if all conditions below are met:

1. A paraphrased Indonesian hadith request is accepted.
2. The system identifies the user's intended request without adding unrelated questions.
3. The system generates several retrieval queries.
4. At least one trusted provider is queried live.
5. Candidate results are normalized into one internal schema.
6. Candidate provenance is identified.
7. A direct provider/resource URL is returned when available.
8. The URL is validated before being labeled a verified direct source.
9. If no reliable source is found, the system explicitly reports that result.
10. The output distinguishes evidence from model-generated explanation.

---

## 6. Core processing pipeline

USER INPUT
→ Input normalization
→ Intent Preservation Engine
→ Claim Reconstruction
→ Ambiguity Gate
→ Domain Router
→ Multi-query Generation
→ Source Router
→ Parallel Live Retrieval
→ Candidate Normalization
→ Source/Provenance Validation
→ Semantic + Lexical Reranking
→ Direct-Link Validation
→ Claim–Evidence Alignment
→ Evidence Pack
→ Limited Referential Clarification
→ USER OUTPUT

---

## 7. Intent Preservation Engine

Input:
- original user text.

Output fields:
- primary_intent;
- explicit_claims;
- inferred_claims;
- not_explicitly_asked;
- entities;
- key_concepts;
- possible_domain;
- ambiguity_score;
- clarification_question.

Rules:
- original input is immutable;
- inferred meaning is never stored as if explicitly stated;
- if ambiguity is material, retrieval stops;
- system asks a clarification question rather than choosing one interpretation.

Example:

Input:
"Kayaknya ada hadis yang bilang kalau cari ilmu dimudahkan jalan ke surga ya?"

Primary intent:
"Find the source of a hadith concerning seeking knowledge and a path to Paradise."

Explicit:
- user believes a hadith may exist;
- concepts: seeking knowledge, path, Paradise.

Not explicit:
- ruling on seeking knowledge;
- who is obligated to study;
- whether every form of study has the same ruling.

---

## 8. Claim Reconstruction

Purpose:
Convert conversational language into a search representation without changing the intended meaning.

Output:
- canonical_claim_id;
- reconstructed_claim;
- search_focus;
- attribution_target;
- domain_candidate.

The reconstructed claim is a retrieval aid, not a religious conclusion.

---

## 9. Ambiguity Gate

Decision states:
- CLEAR;
- LOW_AMBIGUITY;
- MATERIAL_AMBIGUITY.

Suggested initial threshold:
- ambiguity_score < 0.35: continue;
- 0.35–0.60: continue only if one interpretation dominates clearly;
- > 0.60: ask clarification.

Thresholds are provisional and must be calibrated on the test set.

---

## 10. Domain Router

Initial routes:
- QURAN;
- HADITH;
- ACADEMIC;
- INSTITUTIONAL;
- GENERAL_DISCOVERY.

The router does not determine truth. It chooses where the search should begin.

---

## 11. Multi-query Generation

For a single user meaning, generate multiple query forms:
- Indonesian literal query;
- Indonesian semantic paraphrase;
- concept-keyword query;
- English query where useful;
- Arabic concept query where useful;
- candidate Arabic phrase only when generated cautiously and clearly treated as a retrieval query, not as a source quotation.

A generated Arabic candidate MUST NOT be displayed as authenticated text unless retrieved from a validated source.

---

## 12. Live Source Routing

The Source Router selects providers based on domain.

Initial provider families:
- Qur'an provider;
- hadith provider;
- academic metadata provider;
- institutional source provider;
- general-web discovery provider.

Rules:
- use official/structured APIs when available;
- do not scrape providers that prohibit scraping;
- general web is discovery-only until provenance is established;
- provider failure must not terminate the entire pipeline if alternate providers exist.

---

## 13. Candidate normalization

All provider results are converted to a common structure:

- candidate_id;
- provider_id;
- provider_name;
- source_type;
- trust_tier;
- title;
- author_or_compiler;
- collection;
- chapter;
- item_number;
- language;
- retrieved_text;
- source_url;
- source_identifier;
- retrieval_query;
- retrieved_at;
- metadata_complete;
- raw_provider_payload_reference.

---

## 14. Source validation

Source validation is separate from semantic relevance.

Validation checks:
1. provider is registered;
2. access method is permitted;
3. source URL belongs to the expected provider;
4. source identifier is present when the provider supplies one;
5. key metadata is internally consistent;
6. source content is accessible;
7. URL is not a redirect to an unrelated domain;
8. evidence type is correctly labeled.

Trust state:
- PRIMARY_OR_CURATED;
- INSTITUTIONAL;
- ACADEMIC_METADATA;
- DISCOVERY_ONLY;
- UNVERIFIED.

---

## 15. Direct-link validation

A link must never be labeled "verified direct source" merely because a search engine returned it.

Link states:
- VERIFIED_DIRECT: deep link points to the exact source item/passage/resource;
- VERIFIED_PROVIDER: link is on the trusted provider but is broader than the exact item;
- DISCOVERY_ONLY: candidate link found during discovery but primary provenance is not established;
- BROKEN: inaccessible;
- UNVERIFIED: validation incomplete.

Validation:
- HTTPS preferred;
- provider domain match;
- successful HTTP response when technically permissible;
- stable identifier/path where available;
- title/identifier metadata match candidate;
- no unexpected cross-domain redirect.

---

## 16. Retrieval and reranking

Version 1 does not embed a complete local corpus.

Retrieval model:
1. live provider search returns a candidate pool;
2. duplicates are removed;
3. lexical relevance is calculated where text is available;
4. semantic similarity is calculated on candidate text/snippets;
5. a CrossEncoder or equivalent second-stage model reranks the top candidates;
6. source eligibility and link validation are applied;
7. top evidence items are returned.

Important:
- semantic relevance and source authority are separate variables;
- a high semantic score does not upgrade an untrusted source into a primary source.

Initial relevance score for experimentation:

R = 0.40 * semantic_similarity
  + 0.25 * lexical_overlap
  + 0.15 * attribution_match
  + 0.10 * metadata_match
  + 0.10 * multi_query_agreement

Weights are provisional and must be calibrated experimentally.

---

## 17. Claim–evidence alignment

Allowed relationship labels:
- DIRECT_MATCH;
- STRONG_RELATED_MATCH;
- PARTIAL_MATCH;
- ATTRIBUTION_MISMATCH;
- INSUFFICIENT_EVIDENCE.

These labels describe relation to retrieved evidence, NOT religious truth.

---

## 18. Limited clarification policy

The model may say:
- the located source appears to correspond to the user's paraphrase;
- the cited verse/hadith number differs from the source found;
- wording differs from the source;
- the user's phrasing is broader than the retrieved wording;
- the source could not be located;
- further interpretation should be reviewed by a teacher/scholar.

The model may not independently issue substantive religious rulings.

---

## 19. Failure behavior

### Ambiguous intent
Return clarification request. Do not search broadly.

### No provider result
Return:
"No sufficiently relevant source was located through the currently available providers."

### Provider unavailable
Continue other providers and expose provider-unavailable status internally.

### Rate limit
Retry according to provider policy; otherwise continue with alternate providers.

### No validated direct link
Display candidate only with its correct link state. Never fabricate a URL.

### Conflicting high-ranking sources
Present multiple candidates and state that source identification is not yet definitive.

### Evidence too weak for clarification
Return evidence only. Do not generate a corrective conclusion.

---

## 20. Security and privacy

- API credentials must be stored server-side only.
- Secrets must use environment variables or a secret manager.
- Secrets must never be exposed in browser code.
- Uploaded audio/video in later phases should be temporary by default.
- Uploaded files should be deleted after transcription unless the user explicitly opts in to retention.
- Query logs should minimize personal data.
- Third-party provider policies and licenses must be respected.

---

## 21. Initial quality metrics

Core metrics:
- Intent Preservation Accuracy;
- Semantic Drift Rate;
- Domain Routing Accuracy;
- Recall@5;
- Mean Reciprocal Rank;
- Citation/Metadata Accuracy;
- Source-Link Validity;
- Ambiguity Detection Accuracy;
- Response Time;
- Failure Honesty Rate (whether the system correctly says it cannot establish a source).

No metric is a "religious truth accuracy" score.

---

## 22. Initial target values (engineering targets, not claimed results)

- Intent Preservation Accuracy: ≥ 90%
- Semantic Drift Rate: < 10%
- Domain Routing Accuracy: ≥ 90%
- Hadith Recall@5: ≥ 85%
- Qur'an Recall@5: ≥ 95% after Qur'an route is implemented
- Citation/Metadata Accuracy: ≥ 95%
- Source-Link Validity: ≥ 95%
- Ambiguity Detection Accuracy: ≥ 85%
- Median text-query response: < 10 seconds under prototype conditions

These are targets to test, not performance claims.

---

## 23. Definition of done for Phase 1A

Phase 1A is complete when a real Python program can:

Input:
"Kayaknya ada hadis yang intinya orang yang mencari ilmu dimudahkan jalan ke surga."

Then:
1. preserve the intent;
2. generate structured search queries;
3. query at least one hadith provider live;
4. normalize returned candidates;
5. rerank candidates;
6. validate source provenance;
7. return at least one valid provider/direct link when available;
8. state uncertainty honestly;
9. avoid issuing a religious ruling.

Only after this works consistently should a full web UI be built.
