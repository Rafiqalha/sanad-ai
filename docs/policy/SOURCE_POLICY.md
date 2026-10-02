# SANAD.AI — Source Policy v1.0

## 1. Purpose

This document controls which external sources may be used and how SANAD.AI labels them.

The system searches live internet sources. It does not assume that internet availability equals reliability.

---

## 2. Source classes

### Tier 1 — Canonical / curated source provider
Examples:
- recognized Qur'an content/search provider;
- curated hadith provider with documented provenance.

Permitted role:
- primary evidence;
- direct-source linking.

### Tier 2 — Institutional / scholarly source
Examples:
- official religious institution;
- university/repository;
- scholarly publisher or structured scholarly resource.

Permitted role:
- supporting evidence;
- interpretive or institutional context.

### Tier 3 — Academic discovery / metadata
Examples:
- Crossref;
- OpenAlex.

Permitted role:
- discover scholarly literature;
- verify bibliographic metadata;
- provide DOI/publisher links when available.

These services do not automatically establish the religious correctness of an article.

### Encyclopedic / secondary orientation
Example:
- Wikipedia pages fetched through the public MediaWiki API.

Permitted role:
- orientation for people, events, chronology, and historical terminology.

Wikipedia is not primary religious evidence and is never promoted on the basis
of domain reputation alone.

### Tier 4 — General web discovery
Examples:
- general search API results;
- public webpages not in the registry.

Permitted role:
- discover possible source names, titles, or references.

Not permitted:
- automatic promotion to primary evidence.

---

## 3. Initial provider decisions

### Quran Foundation
Status: approved canonical/curated provider.
Role: Qur'an content/search connector.
Access: official server-side OAuth API.
Credential policy: backend only.
Trust boundary:
- semantic candidates must originate from Search API and be hydrated through
  Content API;
- exact references must be resolved against provider chapter metadata;
- Indonesian translation resource IDs must be discovered from provider metadata;
- provider metadata without a live exact-item page is `VERIFIED_PROVIDER`;
- a Quran.com link becomes `VERIFIED_DIRECT` only after host, liveness, and
  same-verse identity validation.

### Sunnah.com
Status: approved candidate hadith provider.
Role: hadith search/data retrieval where supported.
Access: API preferred.
Important restriction:
- do not rely on prohibited scraping;
- API coverage is partial;
- API key is required.

### HadithAPI
Status: approved temporary curated-secondary provider.
Role: structured English/Arabic hadith candidate search before general-web fallback.
Access: documented server-side API with API key.
Trust boundary:
- Tier 2 / supporting evidence only;
- provider response may establish `VERIFIED_PROVIDER` provenance;
- it is not equivalent to Sunnah.com Official API validation;
- it cannot establish `VERIFIED_DIRECT` or Tier-1 primary evidence;
- do not invent a direct-item URL when the provider does not return or document one.

### OpenAlex
Status: approved academic discovery provider.
Role: retrieve research metadata and discovery results.

### Crossref
Status: approved scholarly metadata provider.
Role: DOI and bibliographic verification/discovery.

### Wikipedia / MediaWiki
Status: approved encyclopedic-secondary provider for history queries.
Role: Indonesian-first search with English fallback and actual page-extract fetch.
Trust boundary:
- search snippets are not evidence;
- canonical article URL and extract must come from the MediaWiki response;
- source class is always `ENCYCLOPEDIC`, never primary religious evidence.

### General web search provider
Status: implemented as an independent bounded discovery path.
Role: discovery, provenance leads, metadata, and supporting context only.
Trust boundary:
- at most the configured 2–3 Brave requests per user query;
- duplicate query/result caches reduce repeated paid calls;
- snippets are never final evidence;
- top pages must be fetched, redirect-resolved, readable, live, and relevant;
- fetched pages remain `DISCOVERY_ONLY`, including pages on respected domains;
- credentials are sent only to Brave and never forwarded to destination pages.

---

## 4. Provider registration schema

Each provider must define:
- provider_id;
- provider_name;
- base_domain;
- source_class;
- access_method;
- requires_key;
- allows_server_side_access;
- terms_notes;
- result_identifier_field;
- direct_link_rule;
- expected_metadata;
- timeout_seconds;
- rate_limit_notes;
- enabled.

---

## 5. Evidence promotion rule

A candidate can be displayed as primary evidence only when:
1. it comes from an eligible source class;
2. provenance is established;
3. the candidate identifier/metadata are coherent;
4. the direct link passes validation or the provider supplies an official item URL;
5. the evidence is sufficiently related to the reconstructed claim.

Otherwise it must be displayed with a weaker label.

---

## 6. Direct-link policy

Do not fabricate direct links.

Priority:
1. provider-returned canonical item URL;
2. provider-documented deterministic URL from a verified identifier;
3. verified provider-level result page;
4. discovery link labeled explicitly as discovery-only.

For Quran Foundation, the Quran.com chapter/verse URL may be constructed only
from a verse key returned and identity-validated by Content API. A failed or
mismatched liveness check suppresses the direct-source button.

---

## 7. Web-search policy

General web search is not an authority engine.

If a webpage claims:
"Hadith X is in Book Y"

SANAD.AI should attempt:
1. identify Book Y;
2. query a trusted/official provider for Book Y;
3. locate the passage;
4. return the primary provider link if found.

If primary provenance cannot be established:
- show the web result only as secondary/discovery evidence;
- state that the primary source was not verified.

Web provenance classes are `OFFICIAL_GOVERNMENT`,
`PRIMARY_RELIGIOUS_SOURCE`, `ACADEMIC`, `ENCYCLOPEDIC`, `INSTITUTIONAL`, `PUBLISHER`,
`GENERAL_WEB`, `COMMUNITY`, and `UNKNOWN`. They describe who published a page;
they are not a religious reliability or truth score.

---

## 8. Citation integrity

Every displayed evidence item must retain:
- provider name;
- title/collection;
- item identifier where available;
- direct link state;
- retrieved text/snippet;
- retrieval timestamp;
- query that produced it internally.

No missing metadata may be silently invented.
