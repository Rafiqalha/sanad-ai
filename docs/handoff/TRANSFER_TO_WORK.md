# SANAD.AI — What to Transfer to GPT Work / Codex

## Transfer package

Use the complete ZIP:

`SANAD_AI_Work_Handoff_v1.zip`

This package is intended to be the single handoff artifact.

---

## Files Work/Codex must read BEFORE coding

1. `SPEC.md`
2. `ARCHITECTURE.md`
3. `SOURCE_POLICY.md`
4. `SCHEMAS.md`
5. `TEST_PLAN.md`
6. `LIVE_INTEGRATION_PLAN.md`
7. `CREDENTIALS_AND_ACCESS.md`
8. `WORK_HANDOFF.md`
9. `BUILD_CHECK.md`
10. `README.md`

Then inspect:

- `sanad_core/` (kini `packages/sanad-core/sanad_core/`)
- `tests/`
- `scripts/`
- `source_registry.yaml`

---

## Do NOT transfer secrets

Do not include:
- `.env`
- API keys
- tokens
- passwords
- deployment secrets

`.env.example` is safe because it contains placeholders only.

---

## What you should tell Work/Codex

Paste the content of `WORK_PROMPT.txt`.

Then instruct it to:

1. read every specification file;
2. run tests before modifying code;
3. report missing environment variables;
4. verify current provider adapters;
5. run live smoke tests after secrets are configured;
6. do not build the polished UI until the live source path is proven;
7. preserve epistemic boundaries;
8. never fabricate source metadata or links.

---

## What Work/Codex should return before UI work

Ask for this report first:

### Backend readiness report
- test results;
- package/dependency status;
- environment variables required;
- providers currently reachable;
- live query result for at least one hadith;
- source-link validation result;
- failure modes observed;
- code changes made;
- remaining blockers.

Only after that report is satisfactory should it build the website.

---

## Website acceptance criteria

The first website is acceptable only if:

- user can enter an Indonesian paraphrase;
- system shows the understood intent;
- system shows the reconstructed search claim;
- source candidates are displayed with provider metadata;
- `VERIFIED_DIRECT` is visually distinct from discovery-only;
- direct links are clickable;
- no result is promoted to verified without passing the backend rules;
- insufficient evidence is displayed honestly;
- the site does not issue an autonomous religious verdict;
- API keys remain server-side.
