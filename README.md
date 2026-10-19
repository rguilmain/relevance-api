# relevance-api

A small HTTP API that learns document relevance from historical search-result
clicks.

Each interaction says: for `query` in `index_id`, the user was shown `doc_ids`
in this order and clicked `clicked_doc_id`. The user is assumed to have
examined every doc from the top of the list through the clicked doc, inclusive.
Per `(index_id, query, doc_id)` triple two counters are kept:

- `num_examines`: +1 for every doc at or above the clicked doc's position
- `num_successes`: +1 only for the clicked doc

Learned relevance is `num_successes / num_examines` (always in `0.0..1.0`).

Stack: Python 3.11+, FastAPI, Pydantic v2, uvicorn, stdlib `sqlite3`
(no ORM, parameterized SQL only). Tests use pytest and httpx.

## Requirements

- [`uv`](https://docs.astral.sh/uv/) (used for Python versions, the virtual
  environment, dependencies and running everything)

## Setup

```bash
uv sync
```

`uv sync` creates `.venv`, downloads Python 3.11 (per `.python-version`) and
installs the locked dependencies from `uv.lock`.

## Run the server

```bash
uv run uvicorn app.main:create_app --factory
```

The app is created by the `create_app` factory (there is deliberately no
module-level `app = create_app()`). By default it listens on
`http://127.0.0.1:8000`; add `--host` / `--port` to change that. The SQLite
database directory (`./data`) is created on startup.

## Run the tests

```bash
uv run pytest -q
```

The tests use a temporary SQLite file per test (`tmp_path`), so they never
touch `./data`.

## Configuration

Read from the environment in `Settings.from_env()`; an invalid value fails fast
at startup with a clear error message.

| Variable | Default | Rule |
|---|---|---|
| `DB_PATH` | `./data/relevance.db` | create parent dir if missing |
| `MIN_EXAMINES` | `10` | integer >= 1 |
| `MAX_BATCH_SIZE` | `1000` | integer >= 1 |

```bash
DB_PATH=./data/other.db MIN_EXAMINES=5 uv run uvicorn app.main:create_app --factory
```

## Endpoints

Every endpoint takes a JSON body and uses POST, except the health check.
Invalid input on single-item endpoints returns FastAPI's default 422; batch
endpoints report invalid items per item and always return 200.

### GET /healthz

```bash
curl -s localhost:8000/healthz
```

```json
{"status": "ok"}
```

### POST /v1/interactions

Applies one interaction: every doc from the top of `doc_ids` through
`clicked_doc_id` (inclusive) gets `num_examines + 1`, and only the clicked doc
gets `num_successes + 1`.

```bash
curl -s -X POST localhost:8000/v1/interactions \
  -H "Content-Type: application/json" \
  -d '{"index_id": "products", "query": "  Red   Shoes ", "doc_ids": ["d1","d2","d3","d4"], "clicked_doc_id": "d3"}'
```

```json
{"index_id": "products", "query": "red shoes", "docs_examined": 3}
```

### POST /v1/interactions/batch

`items` must contain 1..`MAX_BATCH_SIZE` entries, otherwise the whole request
gets a 422. Each item is validated with `Model.model_validate`, so a single bad
item does not reject the batch: valid items are applied in order, each in its
own transaction, and invalid ones are reported. The response is always 200.

```bash
curl -s -X POST localhost:8000/v1/interactions/batch \
  -H "Content-Type: application/json" \
  -d '{"items": [
        {"index_id": "products", "query": "red   shoes", "doc_ids": ["d1","d2","d3","d4"], "clicked_doc_id": "d3"},
        {"index_id": "products", "query": "red shoes", "doc_ids": ["d1"], "clicked_doc_id": "nope"}
      ]}'
```

```json
{"results": [
  {"position": 0, "ok": true, "result": {"index_id": "products", "query": "red shoes", "docs_examined": 3}},
  {"position": 1, "ok": false, "error": "clicked_doc_id: clicked_doc_id must be in doc_ids"}
]}
```

### POST /v1/relevance/by-query

Returns learned relevance per doc for one query, using only triples with
`num_examines >= min_examines` (the per-request `min_examines` when given,
otherwise `MIN_EXAMINES`). Results are sorted by relevance DESC, then
`num_examines` DESC, then `doc_id` ASC. An unknown index or query, or nothing
above the cutoff, returns 200 with an empty `docs` list (never 404).

```bash
curl -s -X POST localhost:8000/v1/relevance/by-query \
  -H "Content-Type: application/json" \
  -d '{"index_id": "products", "query": "Red shoes", "min_examines": 1}'
```

```json
{"index_id": "products", "query": "red shoes",
 "docs": [{"doc_id": "d3", "relevance": 0.4}, {"doc_id": "d1", "relevance": 0.1}]}
```

### POST /v1/relevance/by-doc

The same lookup keyed by document: relevance per query for one `doc_id`,
sorted by relevance DESC, then `num_examines` DESC, then `query` ASC.

```bash
curl -s -X POST localhost:8000/v1/relevance/by-doc \
  -H "Content-Type: application/json" \
  -d '{"index_id": "products", "doc_id": "d3", "min_examines": 1}'
```

```json
{"index_id": "products", "doc_id": "d3",
 "queries": [{"query": "red shoes", "relevance": 0.4}]}
```

### POST /v1/relevance/by-query/batch

Same envelope and size rules as the batch update; `result` is the
corresponding single-lookup response and each item may carry its own
`min_examines`.

```bash
curl -s -X POST localhost:8000/v1/relevance/by-query/batch \
  -H "Content-Type: application/json" \
  -d '{"items": [
        {"index_id": "products", "query": "red shoes", "min_examines": 1},
        {"index_id": "products", "query": "   "}
      ]}'
```

```json
{"results": [
  {"position": 0, "ok": true, "result": {"index_id": "products", "query": "red shoes",
   "docs": [{"doc_id": "d3", "relevance": 0.4}, {"doc_id": "d1", "relevance": 0.1}]}},
  {"position": 1, "ok": false, "error": "query: query must not be empty after normalization"}
]}
```

### POST /v1/relevance/by-doc/batch

Same rules, where every item is a single by-doc lookup.

```bash
curl -s -X POST localhost:8000/v1/relevance/by-doc/batch \
  -H "Content-Type: application/json" \
  -d '{"items": [
        {"index_id": "products", "doc_id": "d3"},
        {"index_id": "products", "doc_id": ""}
      ]}'
```

```json
{"results": [
  {"position": 0, "ok": true, "result": {"index_id": "products", "doc_id": "d3",
   "queries": [{"query": "red shoes", "relevance": 0.4}]}},
  {"position": 1, "ok": false, "error": "doc_id: String should have at least 1 character"}
]}
```

## Project layout

```
app/
  __init__.py
  config.py       # Settings dataclass, Settings.from_env()
  normalize.py    # normalize_query()
  models.py       # Pydantic request/response models
  repository.py   # all SQLite access
  main.py         # create_app(settings=None) factory + routes
tests/
pyproject.toml
uv.lock
.python-version
.gitignore
README.md
```

`data/` (the SQLite database directory) and `.venv/` are gitignored.

## Assumptions

Where the spec left something open, the simplest consistent interpretation was
chosen:

1. **Python version.** The project is scaffolded with
   `uv init --app --name relevance-api --python 3.11`, so `.python-version` is
   `3.11` and `requires-python` is `>=3.11` (uv downloads CPython 3.11.x).
2. **Query length is checked after normalization.** `query` has no
   pre-normalization limit: `" ".join(q.lower().split())` is applied first and
   the result must be non-empty and at most 512 characters, so a longer raw
   string that normalizes to <=512 characters is accepted.
3. **`query` must be a string.** Non-string `query` values are rejected (they
   would break `.lower()`), even though the spec spelled out "strings only"
   explicitly for ids.
4. **Ids are stored verbatim.** `index_id`, `doc_id` and `clicked_doc_id` are
   strict strings of 1-512 characters: no coercion, no trimming.
5. **Custom validation messages.** The cross-field and format checks
   (`clicked_doc_id must be in doc_ids`, duplicate/empty `doc_ids`, empty or
   too-long `query`) are raised with `pydantic_core.PydanticCustomError` so
   that `e["msg"]` is used verbatim by the documented
   `"; ".join(f"{loc}: {msg}")` formatter. A plain `ValueError` would make
   pydantic prepend `"Value error, "` and would not match the spec's example.
6. **`min_examines` is strict.** It is `Annotated[StrictInt, Field(ge=1)] | None`,
   so `0`, `"5"` and `5.0` are rejected with 422.
7. **Batch size errors.** An empty `items` list, a missing `items` key, a
   non-list `items`, or more than `MAX_BATCH_SIZE` items all produce a 422 for
   the whole request, via `HTTPException(422)` with a plain `detail` string
   (the spec only fixes the status code).
8. **Batch responses never contain nulls.** Batch handlers return plain dicts
   holding exactly `position`, `ok` and either `result` or `error`.
9. **Relevance is computed in `main.py`.** `repository.py` returns raw
   `(id, num_successes, num_examines)` rows (already ordered); the routes
   divide successes by examines, so the score is never rounded.
10. **Ordering is applied in Python.** Rows above the cutoff are sorted by
    `(-relevance, -num_examines, id)` after fetching, which keeps the
    tie-breaking rules exact and deterministic.
11. **`Settings.from_env()` takes an optional mapping** (defaulting to
    `os.environ`) so tests can inject values. It creates the `DB_PATH` parent
    directory and raises `ValueError` naming the variable and the offending
    value for invalid integers (fail fast at startup).
12. **Connections.** Each repository method opens its own short-lived
    connection (`contextlib.closing` plus `with conn:`) with
    `PRAGMA busy_timeout=5000`; `PRAGMA journal_mode=WAL` is set once in
    `init_schema()` and persists in the database file. Connections are never
    shared across threads and `Depends` is not used.
13. **Startup.** The schema is created idempotently inside
    `create_app(settings=None)`; `None` means `Settings.from_env()`.
14. **No dedupe.** The same `(index_id, query, doc_id)` triple appearing twice
    in one batch is counted twice.
15. **Health check** returns exactly `{"status": "ok"}` with status 200.
16. **Test warning.** pytest prints one Starlette deprecation warning
    (`Using httpx with starlette.testclient is deprecated; install httpx2`).
    The spec's test dependencies are pytest + httpx, and all tests pass.
17. **`min_examines` is capped at the SQLite integer maximum.** The lookup
    models use `Annotated[StrictInt, Field(ge=1, le=2**63 - 1)]`, so a cutoff of
    `2**63` or larger returns 422 for a single lookup, and turns only that item
    into `ok: false` in a batch (the other items are unaffected).
    `Settings.from_env` applies the same bound to `MIN_EXAMINES` and raises
    `ValueError` at startup for e.g. `MIN_EXAMINES=9223372036854775808`.
18. **Unknown request fields are rejected.** `InteractionIn`, `QueryLookupIn`,
    `DocLookupIn` and `BatchRequest` all set
    `model_config = ConfigDict(extra="forbid")`, so an unexpected field is a 422
    on a single-item endpoint, and inside a batch it makes only that item
    `ok: false` (`error` e.g. `unknown_field: Extra inputs are not permitted`)
    while the other items are still applied.
19. **Windows smoke test.** The spec's bash one-liner does not run in
    PowerShell, so the equivalent is used:

```powershell
$p = Start-Process uv -ArgumentList 'run','uvicorn','app.main:create_app','--factory','--port','8000' -PassThru
Start-Sleep -Seconds 5; curl.exe -s localhost:8000/healthz; taskkill /PID $p.Id /T /F
```

