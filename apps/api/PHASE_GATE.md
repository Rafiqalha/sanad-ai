# SANAD.AI — Phase Gate

## Current stage
Phase 1A: hadith-first backend proof of concept.

## Gate A — specification
Status: PASS
- product boundary defined;
- source policy defined;
- schemas defined;
- test plan defined.

## Gate B — static implementation
Status: PASS if BUILD_CHECK.md shows:
- syntax compile = 0;
- mocked tests = passing.

## Gate C — live credentials
Status: PENDING
Required:
- Brave Search API credential;
- Sunnah.com API credential;
- optional OpenAI credential/model for better intent/query generation.

## Gate D — real evidence retrieval
Status: PENDING
Need:
- at least one paraphrased Indonesian question;
- live discovery;
- official-source validation;
- VERIFIED_DIRECT source link;
- no fabricated source.

## Gate E — pilot validation
Status: PENDING
Need:
- 20–40 manually curated cases;
- gold-standard source mappings;
- measured Recall@5 / MRR / link validity / intent preservation.

## Gate F — web UI
Status: BLOCKED until Gate D is passed.
