# SANAD.AI — Handoff ke GPT Work / Codex

## Kapan dipindahkan?

Jangan pindahkan ke Work/Codex untuk membuat UI final sebelum:
1. file dalam paket ini direview;
2. mocked tests lulus;
3. minimal 10–20 live queries sudah diuji dengan API keys;
4. direct-link validation benar-benar bekerja;
5. source failure tidak memicu fabricated citation.

## File yang HARUS dipindahkan

Upload seluruh folder/repository, terutama:

### Dokumen konsep/aturan
- `README.md`
- `WORK_HANDOFF.md`
- `SPEC.md`
- `ARCHITECTURE.md`
- `SOURCE_POLICY.md`
- `SCHEMAS.md`
- `TEST_PLAN.md`
- `source_registry.yaml`

### Core code
- `.env.example` — JANGAN isi dengan secret saat diupload
- `requirements.txt`
- `requirements-ml.txt`
- `pyproject.toml`
- seluruh folder `sanad_core/`
- seluruh folder `tests/`
- `BUILD_CHECK.md`

## File/secret yang JANGAN dikirim sebagai file publik atau commit GitHub

JANGAN upload/commit:
- `.env`
- OpenAI API key
- Brave Search API key
- Sunnah.com API key
- secret deployment apa pun

Secret dimasukkan melalui secret manager/environment variables milik deployment platform.

## Prompt utama untuk Work/Codex

You are implementing SANAD.AI from an existing frozen technical specification.

Read ALL supplied specification files and the Python core before changing anything.

Non-negotiable product rules:
1. SANAD.AI is a source-provenance and retrieval system, not an autonomous religious authority.
2. Preserve the user's intent and do not broaden a question into unrelated religious issues.
3. Evidence must come from live registered providers; model memory is never a source.
4. Search-engine results are discovery-only until provenance is validated.
5. Never fabricate a citation, hadith number, verse number, source title, or URL.
6. Never label a URL as VERIFIED_DIRECT unless the core validation policy passes.
7. Do not convert relevance scores into a religious truth score.
8. If evidence is insufficient, return an explicit insufficient-evidence state.
9. Keep all API keys server-side.
10. Do not change source hierarchy or epistemic boundaries without explicit approval.

Engineering task:
- Preserve the Python core behavior and schemas.
- Run the existing tests first.
- Fix implementation bugs without weakening the specification.
- Add integration tests around provider adapters.
- Build a minimal, clean web interface only after the backend tests pass.
- Expose the backend with FastAPI.
- For the first deployable UI, show:
  a. original question,
  b. understood intent,
  c. reconstructed claim,
  d. primary/source candidates,
  e. provider and metadata,
  f. direct source link with link state,
  g. limitations,
  h. note that substantive religious interpretation remains for qualified teachers/scholars.
- Show provider failures transparently in debug/development mode, but do not expose secrets.
- Do not add deepfake detection, automatic fatwa, complex Digital Sanad Map, full kitab coverage, or automatic religious verdict in v1.

Before implementing new features, report:
A. whether the current tests pass;
B. which environment variables are missing;
C. which provider integrations can be tested live;
D. any mismatch between the specification and current code.

Then implement in small, testable commits.

## Environment variables to configure privately in Work/deployment

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `BRAVE_SEARCH_API_KEY`
- `SUNNAH_API_KEY`

Optional:
- `SANAD_HTTP_TIMEOUT`
- `SANAD_MAX_WEB_RESULTS`
- `SANAD_ENABLE_SEMANTIC_RERANK`
- `SANAD_SEMANTIC_MODEL`

## Work/Codex acceptance checklist

Do not call the site "ready" until:
- backend `/health` works;
- `/v1/search` returns schema-valid JSON;
- ambiguous input stops before retrieval;
- paraphrased hadith input yields candidate evidence;
- at least one real valid source link can be opened;
- broken/unverified links are not shown as verified;
- no API key is present in source code or browser bundle;
- no citation is generated when providers return no evidence.
