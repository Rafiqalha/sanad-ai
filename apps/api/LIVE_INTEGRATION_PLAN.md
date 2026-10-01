# SANAD.AI — Live Integration Test Plan v1

## Objective

Validate that the current Python core can perform a real end-to-end source retrieval without fabricating evidence.

The first live milestone is deliberately narrow:

> Indonesian paraphrase → preserved intent → search query generation → live discovery → canonical hadith reference → official-source validation → direct source link → structured evidence.

Do not build the final website before this milestone is repeatable.

---

## Phase L0 — Environment readiness

Required environment variables:

- `OPENAI_API_KEY` — optional but recommended for intent preservation/query generation.
- `OPENAI_MODEL` — model identifier selected for structured extraction.
- `BRAVE_SEARCH_API_KEY` — required for the current live discovery path.
- `HADITH_API_KEY` — required for the temporary curated-secondary search path.
- `SUNNAH_API_KEY` — required for current official hadith validation.

Optional:

- `SANAD_HTTP_TIMEOUT=12`
- `SANAD_MAX_WEB_RESULTS=10`
- `SANAD_ENABLE_SEMANTIC_RERANK=false`
- `SANAD_SEMANTIC_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

Never commit `.env`.

---

## Phase L1 — Static checks

Run:

```bash
python -m compileall sanad_core
pytest -q
python scripts/check_setup.py
```

Pass condition:
- compilation succeeds;
- all mocked tests pass;
- setup script reports the expected configured/missing providers.

---

## Phase L2 — Provider smoke tests

### L2A — HadithAPI temporary curated search
Goal:
Confirm generated English/Arabic semantic queries return structured candidates.

Pass:
- authenticated endpoint responds;
- returned metadata is normalized without inventing missing fields or URLs;
- result is labeled `VERIFIED_PROVIDER` at most;
- `official_api_validated=false`;
- Brave is not called when a usable HadithAPI candidate exists.

### L2B — Brave fallback discovery
Goal:
Confirm the search API returns Sunnah.com candidates for a known semantic query.

Test:
- input concept: seeking knowledge / path to Paradise;
- domain restriction: `sunnah.com`.

Pass:
- HTTP request succeeds;
- at least one result is returned;
- result contains title + URL;
- discovery result is still labeled discovery-only.

### L2C — Sunnah official API
Goal:
Confirm an already known collection/number can be fetched.

Use a reference that has been manually checked first.

Pass:
- official endpoint responds;
- hadith body/metadata returned;
- provider is `sunnah`;
- `official_api_validated=true`.

### L2D — Direct-link validation
Goal:
Check the exact result link.

Pass:
- provider domain matches;
- link resolves;
- state becomes `VERIFIED_DIRECT` only after official API validation + link validation.

---

## Phase L3 — End-to-end single-case test

Initial query:

> "Katanya kalau orang mencari ilmu dimudahkan jalan menuju surga, hadisnya dari mana?"

Expected behavior:

1. Intent layer identifies source-seeking intent.
2. It does NOT expand into:
   - whether seeking knowledge is obligatory;
   - a fatwa;
   - a legal ruling;
   - a general sermon.
3. Domain = HADITH.
4. Multiple retrieval queries are produced.
5. Discovery finds one or more Sunnah.com candidates.
6. Candidate URL is parsed into collection + identifier if possible.
7. Official API validates the candidate.
8. Result is reranked.
9. Direct link is validated.
10. Output includes:
    - preserved intent;
    - reconstructed claim;
    - source provider;
    - collection/identifier;
    - retrieved evidence text;
    - direct link;
    - link state;
    - limitations;
    - no religious verdict.

---

## Phase L4 — 20-query pilot

Use 20 manually curated Indonesian queries:

- 5 near-exact remembered hadiths;
- 7 paraphrases;
- 3 incomplete memories;
- 3 ambiguous questions;
- 2 unsupported/fabricated statements.

Record:
- correct source expected;
- whether clarification should trigger;
- Top-5 results;
- rank of correct source;
- direct-link status;
- provider errors;
- response time.

Do NOT alter the gold-standard answer after seeing model output.

---

## Phase L5 — Go/no-go gate

Proceed to web UI only if:

- no fabricated citation observed;
- ambiguous inputs stop before broad retrieval;
- at least 80% of pilot cases produce behavior consistent with the gold-standard workflow;
- direct-link validation is reliable on successful source identifications;
- source/provider failures are surfaced honestly.

The 80% value is a development gate, not a scientific performance claim.

---

## Phase L6 — Expand after core success

After hadith-first core is stable:

1. add Qur'an provider adapter;
2. add academic literature adapters;
3. add audio/video transcription;
4. expand trusted-source registry;
5. only then build richer UI/visualization.
