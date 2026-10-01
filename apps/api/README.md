# SANAD.AI Core v0.2

Local-first proof-of-concept for **intent-preserving, source-on-demand Islamic
source retrieval and provenance tracing**.

The repository now includes a lightweight local UI v0 served directly by the
FastAPI backend. It remains an MVP retrieval interface rather than a religious
answering system.

## What v0.2 does

1. Accepts an Indonesian text question.
2. Preserves the user's intent and separates explicit vs inferred meaning.
3. Reconstructs a searchable claim.
4. Generates multiple search queries (Indonesian / English / Arabic when possible).
5. Routes HADITH, QURAN, ISLAMIC_HISTORY, ACADEMIC_ISLAMIC_STUDIES,
   GENERAL_ISLAMIC, and UNKNOWN with a rule-first local multilingual semantic
   fallback.
6. For hadith, searches HadithAPI as structured evidence and can independently
   use a bounded broad Brave path for discovery/provenance; the legacy
   Sunnah-specific Brave fallback remains available when structured retrieval fails.
7. For Qur'an, resolves exact references or searches dynamically through Quran
   Foundation Search API, then hydrates each verse through Content API.
8. Selects an Indonesian translation from live provider resource metadata rather
   than a hard-coded translation ID.
9. Fetches the top broad-web pages with redirect, public-URL, content-type,
   size, liveness, and relevance checks. Web pages always remain `DISCOVERY_ONLY`.
10. Classifies provenance without turning it into a religious truth score.
11. Searches Wikipedia (Indonesian-first), OpenAlex, Crossref, and bounded
    broad web sources for history and academic questions.
12. Ranks candidate evidence and validates direct links before exposing them.
13. Aggregates sanitized improvement patterns without self-training or automatic
    production updates, and provides fail-closed audio/video interfaces for future use.
14. Returns structured provenance, retrieval/cache telemetry, retrieval mode,
   and uncertainty in Indonesian.

## What v0.2 does NOT do

- No fatwa.
- No halal/haram verdict.
- No "religious truth score".
- No database of Qur'an/hadith stored locally.
- No mass scraping of Sunnah.com.
- No automatic final theological judgment.
- No OpenAI API call or paid semantic provider.
- No automatic speech-to-text until a real local engine is configured.

## Required keys for the complete live path

Create `.env` from `.env.example`.

- `OPENAI_API_KEY` / `OPENAI_MODEL` — legacy compatibility fields only; v0.2
  never constructs or calls an OpenAI client.
- `BRAVE_SEARCH_API_KEY` — required for live web discovery.
- `HADITH_API_KEY` — required for temporary curated-secondary hadith search.
- `SUNNAH_API_KEY` — required for official Sunnah.com API validation.
- `QURAN_FOUNDATION_CLIENT_ID` and `QURAN_FOUNDATION_CLIENT_SECRET` — required
  for live Quran Foundation Content/Search access.
- `QURAN_FOUNDATION_ENV` — `prelive` or `production`; prelive has a limited corpus.
- `WIKIPEDIA_LANGS` — defaults to `id,en`.
- `OPENALEX_API_KEY` — optional; keyless/basic mode is supported.
- `CROSSREF_MAILTO` — optional but recommended for polite API identification.
- `CROSSREF_USER_AGENT` — defaults to `SANAD.AI/0.2`.

Without API keys, the project can still run unit tests and heuristic intent/query logic, but the full live evidence path will be unavailable.

## Install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Optional semantic reranking:

```bash
pip install -r requirements-ml.txt
```

## Run CLI

```bash
python -m sanad_core.main "Kayaknya ada hadis yang intinya orang yang mencari ilmu dimudahkan jalan ke surga."
```

## Run local UI and API

```bash
.venv/bin/uvicorn sanad_core.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` for the browser UI. The API remains available at
`POST /v1/search`, and `GET /health` reports backend health.

`railway.toml` preserves Railway/Nixpacks compatibility with a `$PORT`-aware
start command and `/health` deployment probe. This repository is not deployed
automatically; deployment remains an explicit later step.

Then POST:

```json
{
  "text": "Kayaknya ada hadis yang intinya orang yang mencari ilmu dimudahkan jalan ke surga."
}
```

to `/v1/search`.

## Test

```bash
pytest -q
```

## Current engineering status

- Core v2 architecture: implemented.
- Live provider adapters: implemented for Quran Foundation, HadithAPI
  curated-secondary search, a separate bounded broad-web Brave adapter, legacy
  Brave fallback discovery, and Sunnah official API validation.
- Local semantic intent/query layer: implemented; optional remote semantic mode is
  disabled, and the OpenAI SDK is not a runtime dependency.
- Wikipedia, OpenAlex, Crossref, and history/academic aggregation: implemented.
- Local responsive Indonesian-first UI v2: implemented and connected to the live
  FastAPI search endpoint.
- Controlled improvement and multimodal contracts: implemented fail-closed.
- Mocked tests: included.
- Real-world benchmark accuracy: **not yet claimed**; must be measured on a gold-standard set.

## Next milestone

Run 20–40 curated Indonesian paraphrase cases using real API credentials, then calculate:
- Intent Preservation Accuracy
- Semantic Drift Rate
- Recall@5
- MRR
- Metadata Accuracy
- Source-Link Validity
- Failure Honesty Rate
