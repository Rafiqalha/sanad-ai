# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SANAD.AI — an Indonesian-first **source-provenance and retrieval** system for Islamic knowledge. It takes a paraphrased Indonesian question, preserves the intent, generates multilingual search queries, retrieves candidates from live registered providers, and returns validated evidence with honest failure states.

It is explicitly **not** an answering system. Read "Invariants" below before changing any retrieval, ranking, or link logic.

## Repository layout

A pnpm + turbo workspace. The retrieval logic is a library; the HTTP service is one consumer of it.

```text
apps/api/          FastAPI service, scripts, tests, deployment
  app/main.py      HTTP layer — imports sanad_core, serves the UI
  web/index.html   The real browser UI (~1956 lines), served at GET /
  scripts/         check_setup.py + live smoke tests
  tests/           27 hermetic test files
packages/sanad-core/sanad_core/   The library
docs/              Spec, policy, process and handoff documents
infra/             docker-compose.yml
```

- **`apps/web` has no product UI.** It is otherwise-stock `create-next-app` output (Next 16.3.8 / React 19) plus one unused custom API client (`src/lib/api.ts` exports `postSearch`, nothing imports it) and `next dev`-generated agent files. Do not treat it as the product.
- `apps/web/CLAUDE.md` imports `apps/web/AGENTS.md`, which warns that the installed Next.js differs from training data and points at `node_modules/next/dist/docs/`. Heed it before editing that app.
- Docker build contexts are the **repository root**, not the app directories, because `apps/api` depends on the library in `packages/`.
- `railway.toml` lives at the root for the same reason: the Railway service's root directory must be the repository root.
- There is no CI configuration and no `apps/web` deployment config.

## Commands

Run Python commands from `apps/api`. `sanad_core` is resolved via `pyproject.toml`'s `pythonpath`, and `.env` is loaded relative to the working directory.

```bash
python -m pytest -q                                          # full suite
python -m pytest tests/test_orchestrator.py -q                # one file
python -m pytest tests/test_orchestrator.py::test_name -q      # one test
python -m compileall -q app                                    # syntax gate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000     # API + UI at /
python -m sanad_core.main "<question>"                         # CLI, prints response JSON
python scripts/check_setup.py                                  # credential presence report
```

From the repo root:

```bash
corepack pnpm install     # workspace install (turbo + apps/web)
corepack pnpm test        # turbo run test across workspace packages
docker compose -f infra/docker-compose.yml up --build
```

These hit the live internet and **must not be run without real credentials configured**:

```bash
python scripts/live_smoke_test.py                # needs BRAVE_SEARCH_API_KEY + SUNNAH_API_KEY
python scripts/temporary_provider_smoke_test.py  # needs HADITH_API_KEY
```

`check_setup.py` never prints credential values (they appear only as `CONFIGURED`/`MISSING`), though it does print non-secret settings such as `WIKIPEDIA_LANGS`, the Crossref user agent, and the `SANAD_*` knobs. It exits 0 whether credentials are present or missing, and exits 1 only if a settings value fails validation.

### Setup notes

- **Install the library before running the server.** `pip install -r apps/api/requirements.txt` installs `packages/sanad-core` in editable mode. Tests do not need this (pytest resolves the library from source), but `uvicorn` and the CLI do.
- **`apps/api/.venv` is unusable.** It is a POSIX venv built on macOS (`bin/`, `lib/`, no `Scripts/`, darwin-native packages), so the README's `.venv\Scripts\activate` cannot work on Windows. Use a Windows-created venv or a system interpreter with `requirements.txt` installed.
- **`pyproject.toml` declares no dependencies.** `packages/sanad-core/pyproject.toml` owns the library's dependencies; `apps/api/requirements.txt` holds the service's plus an editable path to the library. `requirements-ml.txt` pulls the library's optional `ml` extra.
- **Known failure:** `tests/test_structured_provider_cache_security.py::test_check_setup_reports_only_credential_presence` fails on Windows (274 pass, 1 fail). The test spawns `check_setup.py` in a subprocess with a minimal `env=` dict that omits `SystemRoot`, so Winsock cannot initialize (`OSError: [WinError 10106]`) during `import asyncio`. This is a test-harness portability bug, not a product bug — don't "fix" it by relaxing the assertion it guards.
- **`turbo` may be blocked by Windows Application Control.** On some Windows machines the OS refuses to execute turbo's native binary (`An Application Control policy has blocked this file`), so `pnpm test` fails while everything else works. That is an environment restriction, not a repo defect. The configuration itself is valid against turbo 2.x's schema.

## Architecture

### Request pipeline

`POST /v1/search` → `SanadOrchestrator.search()` in `packages/sanad-core/sanad_core/orchestrator.py`. `search()` wraps `_search()` with timing and improvement-signal recording; `_search()` runs the HADITH / QURAN / GENERAL_ISLAMIC / UNKNOWN flow, while `_search_history_and_academic()` handles ISLAMIC_HISTORY and ACADEMIC_ISLAMIC_STUDIES:

1. `IntentEngine.analyze()` → `LocalSemanticRouter.route()`. Routing is rule-first regex, then a dependency-free fuzzy prototype scorer (`rapidfuzz` token-set plus character-ngram cosine). **Fully local — no model, no network, no OpenAI.**
2. Ambiguity gate: `ambiguity_score > 0.60` returns `NEEDS_CLARIFICATION` and stops before any retrieval.
3. `IntentEngine.reconstruct()` → `ReconstructedClaim`.
4. Route by domain:
   - **HADITH** → `HadithRetrievalPipeline` (`retrieval.py`): HadithAPI structured search first → legacy Sunnah-restricted Brave fallback → Sunnah.com Official API validation when an exact reference parses.
   - **QURAN** → `QuranRetrievalPipeline`: Quran Foundation only. Exact references bypass the Search API; semantic requests go Search API → Content API hydration. Brave is never used here.
   - **ISLAMIC_HISTORY** / **ACADEMIC_ISLAMIC_STUDIES** → `history_pipeline.py`: MediaWiki (Indonesian-first) + OpenAlex + Crossref + a bounded Brave branch. Returns `web_results`, not `evidence`.
   - **GENERAL_ISLAMIC** / **UNKNOWN** → clarification or no-source response.
5. `WebDiscoveryPipeline` (`web_retrieval.py`) — an independent provenance branch. It can run alongside structured hadith retrieval but **never promotes, replaces, or upgrades structured evidence**.
6. `Reranker.rank()` scores with `R = 0.40*semantic + 0.25*max(lexical, concept_overlap) + 0.15*attribution_match + 0.10*metadata_match + 0.10*multi_query`, where `semantic` falls back to the lexical score unless the optional sentence-transformers reranker is enabled (off by default). The **orchestrator**, not the reranker, then slices the top 5.
7. `SourceLinkResolver.validate()` concurrently per candidate, then `build_evidence()` classifies the relation and attaches limitations.
8. `FinalResponse` with generated queries, telemetry, `retrieval_mode`, and `provider_errors`. All user-facing strings are Indonesian.

`SourceLinkResolver` is a thin re-export shim (`source_link_resolver.py`); the implementation is `link_validator.py`, which also exposes `DirectLinkValidator` as a backward-compatible alias.

### Evidence and link states — the core invariant system

This is the part to understand before touching anything:

- `LinkState` (`schemas.py`): `VERIFIED_DIRECT` → `VERIFIED_PROVIDER` → `DISCOVERY_ONLY` / `BROKEN` / `UNVERIFIED`.
- **For structured evidence, `LinkState` is decided solely by `SourceLinkResolver.validate()` in `link_validator.py`; provider adapters only set boolean validation flags and never compute link states.** Discovery records outside that path (broad-web pages, history sources) hard-code `DISCOVERY_ONLY` and are never promoted. Brave hits are always `DISCOVERY_ONLY`; HadithAPI caps at `VERIFIED_PROVIDER`.
- `VERIFIED_DIRECT` requires exact item identity — the candidate URL must itself identify the exact item, the final response must either land on that item's URL or (for Quran.com slug redirects) carry an explicit same-verse marker in the live page, and the canonical `source_identifier` must match — plus a live 200 HTTPS response that stayed inside the registered provider domains, complete metadata, and the provider-specific validation flag.
- `Candidate` carries **three deliberately separate** validation flags: `official_api_validated` (set only by the Sunnah.com path), `canonical_provider_validated` (Quran Foundation identity), and `provider_api_validated` (a generic structured-response flag set by HadithAPI *and* by the Quran provider). The separation is load-bearing: evidence eligibility ignores `provider_api_validated` for HadithAPI, which is additionally capped at `VERIFIED_PROVIDER`.
- `eligible_for_primary_evidence()` in `evidence.py` gates primary evidence on registry eligibility + trust tier + complete metadata + a canonical identifier + provider validation + `VERIFIED_DIRECT` + provider domain match + exact identity match. Weakening any conjunct silently promotes unverified content.
- `EvidenceRelation` and `SourceClass` describe relation-to-retrieved-evidence and *who published a page*. Neither is a truth score, and the code comments say so repeatedly.
- `REGISTRY` in `source_registry.py` is the **enforced** allow-list (domains, `trust_tier`, `evidence_role`); it drives both link validation and evidence eligibility. `apps/api/source_registry.yaml` is descriptive only — runtime never reads it, only a test does.

### Providers

`providers/base.py` declares ABCs (`DiscoveryProvider`, `EvidenceProvider`, `CuratedSearchProvider`, `QuranEvidenceProvider`), but history/academic providers are duck-typed against `search(query, *, limit=...)`. To add a provider: a new module under `sanad_core/providers/`, normalize the payload inside the adapter, and wire it directly into the relevant pipeline by import/construction (there is no plugin registry). Add it to `REGISTRY` **only if it emits `Candidate`s for the evidence path** — Wikipedia, OpenAlex, Crossref and broad-web Brave are deliberately absent, because a `REGISTRY` entry is what grants evidence and link eligibility. Gate optional subsystems with `sanad_enable_*` flags, or by credential presence (HadithAPI is enabled by `settings.hadith_api_key`). Keep the `transport=` constructor kwarg — tests inject `httpx.MockTransport` through it.

Missing-credential behavior is deliberately uneven: Brave (`RuntimeError`), Sunnah (`RuntimeError`), HadithAPI (`HadithAPIError`) and the Quran provider (`QuranProviderUnavailable`) **raise**; `BroadWebDiscoveryProvider` does not — it returns no hits and records the error in the returned batch's `errors`. MediaWiki, OpenAlex and Crossref need no credentials at all (Wikipedia is keyless; the OpenAlex key and Crossref `mailto` are optional) and only append to `last_errors` when an HTTP call actually fails. Provider isolation and partial success are deliberate — one failing provider must not fail the request.

### Configuration

`sanad_core/config.py` exposes a pydantic-settings singleton `settings`, loading `.env` **relative to CWD**. Hard caps worth knowing: `sanad_max_brave_requests` ≤ 3 (default 2), `sanad_max_web_pages` ≤ 5 (default 3), `sanad_web_max_content_bytes` (default 750 KB), and in-memory process-local TTL caches. Link validation and the page fetcher each follow redirects in a loop capped at **6 HTTP requests** (so at most 5 redirects); exceeding it yields `UNVERIFIED`.

`OPENAI_API_KEY` / `OPENAI_MODEL` exist **for legacy compatibility only** — no OpenAI client is constructed or called, and `SANAD_ENABLE_REMOTE_SEMANTIC` defaults to `false`. Intent analysis, query generation, routing, and reranking all run locally.

## Invariants — do not weaken these

From `docs/handoff/WORK_HANDOFF.md`, `docs/policy/SOURCE_POLICY.md` and `docs/spec/SPEC.md`, and enforced in code:

- Never fabricate a citation, hadith number, verse number, translation, source title, or URL. Missing metadata is never invented.
- Evidence comes only from live registered providers; model memory is never a source.
- Search-engine results and fetched web pages stay discovery-only until provenance is validated — including pages on respected domains.
- Never label a link `VERIFIED_DIRECT` unless the validation policy actually passes.
- Do not convert relevance scores into a religious truth score, and do not issue fatwas, halal/haram verdicts, or final theological conclusions.
- Keep all API keys server-side and out of the browser bundle. `HADITH_API_KEY` is sent as a **query parameter**, so never log or report full provider request URLs.
- Do not change source hierarchy or epistemic boundaries without explicit human approval.
- `ImprovementWorkflow.apply_to_production()` and `.self_train()` exist to raise `AutomaticUpdateProhibitedError`. Keeping them as raising stubs *is* the policy — there is no automatic self-training or production-update path.
- `multimodal.py` base classes are fail-closed by design: they report unavailable and raise rather than emit a fabricated transcript or claim.

## Testing

The suite under `apps/api/tests/` is fully hermetic — no test needs network access or credentials, and they assert the fail-closed no-key behavior. There is **no `conftest.py` and no shared fakes module** — fakes are defined per-file. No custom markers are registered, though `@pytest.mark.asyncio` and `@pytest.mark.parametrize` appear widely; `asyncio_mode = "auto"` makes the asyncio marker unnecessary.

Three mocking patterns dominate (not exclusively — tests also monkeypatch `app.main.orchestrator`, use `monkeypatch.setenv` / `chdir`, and inject fakes into pipelines other than the orchestrator):

1. **`httpx.MockTransport` injected via a provider's `transport=` kwarg** — `test_quran_provider.py`, `test_history_pipeline.py` (transport factories), `test_brave_provider.py`.
2. **`monkeypatch.setattr(settings, "<field>", ...)`** on the config singleton — `test_quran_provider.py`, `test_hadithapi_fallback.py`, `test_broad_web_discovery.py`.
3. **Duck-typed fakes passed to the `SanadOrchestrator(...)` constructor** — `test_orchestrator.py` (`FakeIntent`/`FakeQueries`/`FakeRetrieval`/`FakeReranker`/`FakeLink`) and `test_mocked_live_pipeline.py` (end-to-end).

Test files read `source_registry.yaml` and `.env.example` via `Path(__file__).resolve().parents[1]`, which is why both stay in `apps/api/` rather than moving into the library. `tests/test_live_smoke_gate.py` imports `scripts.live_smoke_test` as a namespace package, so `scripts/` must remain exactly one level below the pythonpath root.

Traps that break tests easily:

- `.env` is loaded at import into the global `settings` singleton, so ambient real credentials leak into tests that construct providers with defaults. Prefer `monkeypatch.setattr`; use `Settings(_env_file=None)` for isolated env parsing.
- Tests assert **exact Indonesian strings** — including the typographic apostrophe (U+2019) in `"Sumber Qur’an belum dapat diakses saat ini."` — and **exact telemetry counts**. Copy and ranking changes break many tests at once; expect it and update deliberately.
- `test_ui_api.py` pins `{"status": "ok", "version": "0.1.0"}` and asserts `GET /` works after `monkeypatch.chdir(tmp_path)`, which is why `WEB_ROOT` in `app/main.py` must stay absolute.
- `test_structured_provider_cache_security.py::test_env_example_keeps_all_credentials_blank` requires each of its eight listed credential keys to be blank in `.env.example` — other entries (`QURAN_FOUNDATION_ENV`, `WIKIPEDIA_LANGS`, `CROSSREF_USER_AGENT`, the `SANAD_*` knobs) are non-blank by design.
- `tests/test_history_pipeline.py` imports the private helpers `_merge_duplicate_sources` and `_source_query_fit` from `sanad_core.history_pipeline` — keep those importable.
- `tests/live_cases.json` is a manual evaluation dataset; no code reads it.

## Environment

Copy `apps/api/.env.example` to `apps/api/.env`. Required for the full live path: `BRAVE_SEARCH_API_KEY`, `HADITH_API_KEY`, `SUNNAH_API_KEY`, `QURAN_FOUNDATION_CLIENT_ID`, `QURAN_FOUNDATION_CLIENT_SECRET` (plus `QURAN_FOUNDATION_ENV=prelive|production`). Optional: `OPENALEX_API_KEY` (keyless mode works), `CROSSREF_MAILTO`, `WIKIPEDIA_LANGS`, and the `SANAD_*` tuning knobs. Credentials belong in `.env` only — never in the spec, frontend code, commits, or screenshots. Note that `docker compose config` interpolates `env_file` and will print their values; avoid running it where output is captured.

## Current stage

Per `docs/process/PHASE_GATE.md` the project is at **Phase 1A** (hadith-first backend proof of concept). `docs/handoff/WORK_PROMPT.txt` and `PHASE_GATE.md` gate the web UI: **Gate F is BLOCKED until Gate D passes**, and the standing instruction is not to build the final website until a real-credential backend readiness report has been reviewed and approved. Live benchmark accuracy is **not yet claimed** — the metrics in `SPEC.md` §22 are engineering targets, not results.
