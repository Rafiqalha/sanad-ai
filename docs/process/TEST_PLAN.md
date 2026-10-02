# SANAD.AI — v2 Test Plan

## Goal

Validate the retrieval core before building the full website.

Phase 1A remains text-only and now covers both hadith and Qur'an provenance.
v2 also covers Islamic history, academic discovery, fetched-page provenance,
controlled improvement, and fail-closed future multimodal contracts.

---

## Test groups

### A. Exact or near-exact remembered meaning
Examples:
- "Ada hadis tentang amal tergantung niat?"
- "Hadis yang bilang agama itu nasihat apa sumbernya?"

Expected:
- intent preserved;
- correct domain;
- relevant hadith candidate in Top 5;
- valid provider link when available.

### B. Indonesian paraphrase
Examples:
- "Kalau orang berjalan untuk mencari ilmu katanya dipermudah ke surga, sumbernya apa?"
- "Ada hadis bahwa Allah melihat hati dan amal, bukan penampilan?"

Expected:
- paraphrase reconstruction works;
- semantic retrieval retrieves relevant candidate.

### C. Incomplete memory
Examples:
- "Hadis yang ada kata dunia penjara orang mukmin itu apa ya?"
- "Yang tentang orang kuat bukan yang menang bergulat itu hadis mana?"

Expected:
- query expansion;
- source retrieval;
- no invented missing wording.

### D. Ambiguous query
Examples:
- "Ada dalil tentang jalan itu?"
- "Hadis tentang hati apa ya?"

Expected:
- clarification request;
- no premature broad search.

### E. Wrong attribution
Example:
- user says a statement is from Bukhari when provider evidence points elsewhere.

Expected:
- system reports attribution mismatch carefully;
- no religious conclusion.

### F. Unsupported / no-source case
Example:
- fabricated aphorism attributed to the Prophet.

Expected:
- NO_RELIABLE_SOURCE_FOUND or weak evidence;
- no hallucinated reference.

### G. Provider failure
Simulate:
- timeout;
- invalid API key;
- rate limit.

Expected:
- partial failure handled;
- alternate provider path continues if available.

### H. Direct-link validation
Cases:
- correct deep link;
- provider homepage only;
- broken link;
- redirect to another domain.

Expected:
- correct link state.

### I. Qur'an dynamic retrieval

Cases:
- exact numeric and named-surah references;
- Indonesian semantic queries;
- unseen semantic queries not present in router/query rules;
- dynamic Indonesian translation resource ID;
- missing credentials, scope errors, and incomplete provider metadata.

Expected:
- exact requests bypass Search API and use provider chapter metadata;
- semantic requests call Search API, then fetch Content API details for returned
  verse keys;
- no phrase-to-verse lookup table or fabricated fallback;
- Arabic text is preserved and provider translation markup is rendered as text;
- direct links require a live same-verse identity check.

### J. Islamic history and academic retrieval

Cases:
- Indonesian and unseen history questions;
- Indonesian-first Wikipedia with English fallback;
- OpenAlex keyless/keyed metadata;
- Crossref search and exact DOI validation;
- same-URL structured metadata vs Brave fetched-page boundary;
- unrelated structured results with high provenance but low relevance.

Expected:
- actual page extracts, not search snippets;
- academic/encyclopedic sources remain non-religious-authority context;
- no discovery page body inherits `VERIFIED_PROVIDER`;
- max two Brave requests with cache telemetry.

### K. UX, security, and future capability contracts

Expected:
- desktop/mobile UI hides raw machine states;
- Arabic remains readable and RTL;
- frontend contains no provider credentials or token headers;
- improvement observations are sanitized and cannot self-train/release;
- unconfigured audio/video interfaces fail without fabricating transcripts.

---

## Initial dataset

Start with 40 manually curated cases:
- 10 exact/near-exact;
- 10 paraphrases;
- 5 incomplete-memory;
- 5 ambiguous;
- 4 wrong attribution;
- 4 unsupported;
- 2 provider/link failure scenarios.

Expand to 100 cases after Phase 1A stabilizes.

---

## Metrics

1. Intent Preservation Accuracy
2. Semantic Drift Rate
3. Domain Routing Accuracy
4. Recall@5
5. Mean Reciprocal Rank
6. Metadata Accuracy
7. Source-Link Validity
8. Ambiguity Detection Accuracy
9. Median Response Time
10. Failure Honesty Rate

---

## Human gold standard

Each test case should contain:
- intended meaning;
- correct domain;
- expected source where known;
- correct direct/provider URL;
- whether clarification should be required;
- acceptable candidate variants;
- expert note if interpretation-sensitive.

A qualified reviewer should verify the gold-standard religious source mappings used for evaluation.
