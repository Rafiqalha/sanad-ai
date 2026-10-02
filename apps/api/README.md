# @sanad/api

The HTTP service layer for SANAD.AI. It wires the `sanad-core` library into a
FastAPI application and serves the browser UI.

Retrieval, ranking, and evidence logic do **not** live here — see
[`packages/sanad-core`](../../packages/sanad-core). This package owns the
deployable service, the operational scripts, and the test suite.

## Run

Run everything from this directory: `sanad_core` and the `scripts` namespace
package are resolved relative to it, and `.env` is loaded relative to the
working directory.

```bash
pip install -r requirements.txt          # includes the sanad-core library
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> for the UI.

Optional local semantic reranker (large download):

```bash
pip install -r requirements-ml.txt
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Browser UI (`web/index.html`) |
| `GET` | `/health` | Health probe used by the deploy healthcheck |
| `POST` | `/v1/search` | `{"text": "..."}` → structured response |

## Test

```bash
python -m pytest -q                             # all 275
python -m pytest tests/test_orchestrator.py -q  # one file
python -m pytest tests/test_ui_api.py::test_root_is_independent_of_working_directory -q
```

The suite is fully hermetic — no test needs network access or credentials.

`test_check_setup_reports_only_credential_presence` fails on Windows only: it
runs `check_setup.py` in a subprocess whose minimal environment omits
`SystemRoot`, so Winsock cannot initialise. That is a test-harness portability
bug, not a product bug.

## Layout

```text
app/main.py    FastAPI application (imports sanad_core, serves web/)
web/           Browser UI served at GET /
scripts/       check_setup.py and the live smoke tests
tests/         27 hermetic test files
```

`source_registry.yaml` and `.env.example` live here rather than in the library
because the test suite reads them relative to this directory.
