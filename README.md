# SANAD.AI

Intent-preserving Islamic source provenance and retrieval.

SANAD.AI takes a paraphrased Indonesian question, preserves what the user
actually meant, generates multilingual search queries, retrieves candidates
from live registered providers, and returns validated evidence with honest
failure states.

> Understand the intent → trace the source → show the evidence → leave
> substantive religious judgment to qualified scholarship.

**It is not an answering system.** It does not issue fatwas, does not rule on
halal/haram, and does not produce a "religious truth score". See
[docs/spec/SPEC.md](docs/spec/SPEC.md) for the epistemic boundaries.

## Repository layout

```text
apps/
  api/        FastAPI service, retrieval entry points, tests, deployment
  web/        Next.js app (scaffold — no product UI yet)
packages/
  sanad-core/ Python library: schemas, providers, ranking, evidence, orchestration
docs/         Specifications, policies, plans and handoff notes
infra/        Docker Compose
```

The real user interface today is a single self-contained page served by the API
at `GET /`. `apps/web` is still `create-next-app` scaffolding.

## Quickstart

Requires Python 3.11+ and Node 24+ (for the workspace tooling).

```bash
# 1. Install the retrieval library and service dependencies.
#    Run this from the repository root: pip resolves the library path in
#    requirements.txt against the working directory, not the file.
pip install -r apps/api/requirements.txt

# 2. Configure credentials (all optional — see below)
cp apps/api/.env.example apps/api/.env

# 3. Run the API and UI
cd apps/api
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> for the UI. `POST /v1/search` accepts
`{"text": "..."}` and `GET /health` reports backend health.

Without any API keys the project still runs: intent analysis, routing, query
generation and the full test suite all work offline. Only the live evidence
path needs credentials.

```bash
python scripts/check_setup.py   # which credentials are present
```

### JavaScript workspace

```bash
corepack enable pnpm   # if pnpm is not already available
pnpm install
pnpm test              # runs every workspace package's tests via turbo
```

## Commands

Run Python commands from `apps/api` — the package is importable from there and
`.env` is loaded relative to the working directory.

```bash
python -m pytest -q                             # full test suite
python -m pytest tests/test_orchestrator.py -q  # one file
python -m compileall -q app                     # syntax check
python -m sanad_core.main "<question>"          # CLI, prints response JSON
```

Live smoke tests hit real providers and need real credentials:

```bash
python scripts/live_smoke_test.py               # BRAVE_SEARCH_API_KEY + SUNNAH_API_KEY
python scripts/temporary_provider_smoke_test.py # HADITH_API_KEY
```

### Docker

```bash
docker compose -f infra/docker-compose.yml up --build
```

Build contexts are the repository root, because the API service depends on the
`packages/sanad-core` library.

## Configuration

Copy `apps/api/.env.example` to `apps/api/.env`. Required for the full live
path: `BRAVE_SEARCH_API_KEY`, `HADITH_API_KEY`, `SUNNAH_API_KEY`,
`QURAN_FOUNDATION_CLIENT_ID`, `QURAN_FOUNDATION_CLIENT_SECRET`.
`OPENALEX_API_KEY`, `CROSSREF_MAILTO` and `WIKIPEDIA_LANGS` are optional.
`OPENAI_API_KEY` exists only for legacy compatibility — no OpenAI client is
constructed. Credentials belong in `.env` and nowhere else.

## Documentation

| Path | Contents |
| --- | --- |
| [docs/spec/](docs/spec/) | Product spec, architecture, schemas |
| [docs/policy/](docs/policy/) | Source policy, credentials and access |
| [docs/process/](docs/process/) | Phase gate, test plan, build checks |
| [docs/integration/](docs/integration/) | Live integration plan |
| [docs/handoff/](docs/handoff/) | Work handoff notes and prompts |

## Status

Phase 1A — hadith-first backend proof of concept. Benchmark accuracy is **not
yet claimed**; the metric targets in the spec are goals, not results. See
[docs/process/PHASE_GATE.md](docs/process/PHASE_GATE.md).
