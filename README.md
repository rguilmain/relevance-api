# relevance-api

A small HTTP API that learns document relevance from historical search-result
clicks.

## How learning works

Each interaction says: for `query` in `index_id`, the user was shown `doc_ids`
in this order and clicked `clicked_doc_id`. The user is assumed to have
examined every doc from the top of the list through the clicked doc, inclusive.
Per `(index_id, query, doc_id)` triple two counters are kept:

- `num_examines`: +1 for every doc at or above the clicked doc's position
- `num_successes`: +1 only for the clicked doc

Learned relevance is `num_successes / num_examines` (always in `0.0..1.0`).
Lookups only include docs whose `num_examines` is at least `min_examines` (the
per-request value when given, otherwise the `MIN_EXAMINES` setting, default
`10`); everything below the cutoff is omitted. On a fresh database, lookups
therefore return empty lists until some triples reach that cutoff. The examples
below pass `min_examines: 1` so results show up immediately.

Stack: Python, FastAPI, Pydantic v2, uvicorn, stdlib `sqlite3` (no ORM,
parameterized SQL only). Tests use pytest and httpx.

## Security

There is no authentication: anyone who can reach the API can write to the
database. Run it behind your own gateway or on a private network. The default
bind address is `127.0.0.1`; do not pass `--host 0.0.0.0` without a gateway in
front.

## Requirements

- Python 3.11+ (`.python-version` is `3.11`; `uv` downloads it if needed)
- [`uv`](https://docs.astral.sh/uv/), used for Python versions, the virtual
  environment, dependencies and running everything

## Setup

```bash
uv sync
```

This creates `.venv` and installs the locked dependencies from `uv.lock`.

## Run the server

```bash
uv run uvicorn app.main:create_app --factory
```

The app is created by the `create_app` factory (there is deliberately no
module-level `app = create_app()`). By default it listens on
`http://127.0.0.1:8000`; add `--host` / `--port` to change that. The database
directory (`./data` by default) is created on startup.

FastAPI's generated docs are served at `/docs` (Swagger UI) and `/redoc`
(ReDoc), with the raw schema at `/openapi.json`. The two UIs load their
JavaScript from a CDN, so they need internet access. The batch endpoints accept
a loosely typed `items` list (so one bad item can't reject the whole batch), so
their schemas are less detailed than the single-item endpoints.

## Run the tests

```bash
uv run pytest -q
```

Each test uses a temporary SQLite file and working directory, so the tests
never touch `./data`.

## Configuration

Read from the environment in `Settings.from_env()`; an invalid value fails fast
at startup with a clear error message.

| Variable | Default | Rule |
|---|---|---|
| `DB_PATH` | `./data/relevance.db` | parent directory is created if missing |
| `MIN_EXAMINES` | `10` | integer from 1 to 2**63 - 1 |
| `MAX_BATCH_SIZE` | `1000` | integer >= 1 |

```bash
DB_PATH=./data/other.db MIN_EXAMINES=5 uv run uvicorn app.main:create_app --factory
```

## Endpoints

Every endpoint takes a JSON body and uses POST, except the health check.
Invalid input on single-item endpoints returns FastAPI's default 422; batch
endpoints report invalid items per item and always return 200.

The examples build on each other: run them in order against a fresh database.
They use bash syntax. In PowerShell, pipe the JSON into `curl.exe` instead:

```powershell
'{"index_id":"products","query":"red shoes","min_examines":1}' |
  curl.exe -s -X POST localhost:8000/v1/relevance/by-query -H "Content-Type: application/json" --data-binary "@-"
```

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

Here `d1`, `d2` and `d3` are examined and `d3` is the success. `d4` was shown
below the click and is untouched.

### POST /v1/interactions/batch

`items` must contain 1 to `MAX_BATCH_SIZE` entries, otherwise the whole request
gets a 422. Each item is validated individually, so a single bad item does not
reject the batch: valid items are applied in order, each in its own
transaction, and invalid ones are reported. The response is always 200.

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
`num_examines >= min_examines`. Results are sorted by relevance descending,
then `num_examines` descending, then `doc_id` ascending. An unknown index or
query, or nothing above the cutoff, returns 200 with an empty `docs` list
(never 404).

```bash
curl -s -X POST localhost:8000/v1/relevance/by-query \
  -H "Content-Type: application/json" \
  -d '{"index_id": "products", "query": "Red shoes", "min_examines": 1}'
```

```json
{"index_id": "products", "query": "red shoes",
 "docs": [{"doc_id": "d3", "relevance": 1.0},
          {"doc_id": "d1", "relevance": 0.0},
          {"doc_id": "d2", "relevance": 0.0}]}
```

### POST /v1/relevance/by-doc

The same lookup keyed by document: relevance per query for one `doc_id`,
sorted by relevance