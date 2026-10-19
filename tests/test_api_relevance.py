from fastapi.testclient import TestClient

import pytest

from app.config import Settings
from app.main import create_app


def record(client, index_id="products", query="shoes", doc_ids=("d1",), clicked_doc_id="d1"):
    """Post one interaction and return the parsed response."""
    response = client.post(
        "/v1/interactions",
        json={
            "index_id": index_id,
            "query": query,
            "doc_ids": list(doc_ids),
            "clicked_doc_id": clicked_doc_id,
        },
    )
    assert response.status_code == 200
    return response.json()


def lookup(client, body):
    return client.post("/v1/relevance/by-query", json=body)


def lookup_doc(client, body):
    return client.post("/v1/relevance/by-doc", json=body)


# --- shape and unknown keys -------------------------------------------------


def test_unknown_query_returns_empty_docs(client):
    response = lookup(
        client, {"index_id": "products", "query": "Red shoes", "min_examines": 1}
    )

    assert response.status_code == 200
    assert response.json() == {
        "index_id": "products",
        "query": "red shoes",
        "docs": [],
    }


def test_unknown_index_returns_empty_docs(client):
    record(client, index_id="products")

    response = lookup(client, {"index_id": "articles", "query": "shoes", "min_examines": 1})

    assert response.status_code == 200
    assert response.json() == {"index_id": "articles", "query": "shoes", "docs": []}


def test_by_query_returns_relevance_per_doc(client):
    record(client, doc_ids=["d1", "d2"], clicked_doc_id="d2")
    record(client, doc_ids=["d1", "d2"], clicked_doc_id="d1")

    response = lookup(client, {"index_id": "products", "query": "shoes", "min_examines": 1})

    assert response.status_code == 200
    assert response.json() == {
        "index_id": "products",
        "query": "shoes",
        # d2: 1 success / 1 examine; d1: 1 success / 2 examines
        "docs": [
            {"doc_id": "d2", "relevance": 1.0},
            {"doc_id": "d1", "relevance": 0.5},
        ],
    }


def test_by_doc_returns_relevance_per_query(client):
    record(client, query="first", doc_ids=["d1", "d2"], clicked_doc_id="d2")
    record(client, query="second", doc_ids=["d1"])

    response = lookup_doc(client, {"index_id": "products", "doc_id": "d1", "min_examines": 1})

    assert response.status_code == 200
    assert response.json() == {
        "index_id": "products",
        "doc_id": "d1",
        "queries": [
            {"query": "second", "relevance": 1.0},
            {"query": "first", "relevance": 0.0},
        ],
    }


def test_by_doc_unknown_doc_returns_empty_queries(client):
    response = lookup_doc(client, {"index_id": "products", "doc_id": "nope"})

    assert response.status_code == 200
    assert response.json() == {"index_id": "products", "doc_id": "nope", "queries": []}


# --- min_examines -----------------------------------------------------------


def test_default_min_examines_hides_nine_examines_and_shows_ten(client):
    for _ in range(9):
        record(client)

    hidden = lookup(client, {"index_id": "products", "query": "shoes"})
    assert hidden.status_code == 200
    assert hidden.json()["docs"] == []

    record(client)

    shown = lookup(client, {"index_id": "products", "query": "shoes"})
    assert shown.json()["docs"] == [{"doc_id": "d1", "relevance": 1.0}]


def test_per_request_min_examines_overrides_the_default(client):
    for _ in range(3):
        record(client)

    assert lookup(client, {"index_id": "products", "query": "shoes"}).json()["docs"] == []
    assert lookup(
        client, {"index_id": "products", "query": "shoes", "min_examines": 3}
    ).json()["docs"] == [{"doc_id": "d1", "relevance": 1.0}]
    assert lookup(
        client, {"index_id": "products", "query": "shoes", "min_examines": 4}
    ).json()["docs"] == []


def test_min_examines_default_from_settings_is_honored(make_app):
    with TestClient(make_app(min_examines=3)) as custom_client:
        for _ in range(3):
            record(custom_client)

        assert lookup(custom_client, {"index_id": "products", "query": "shoes"}).json()[
            "docs"
        ] == [{"doc_id": "d1", "relevance": 1.0}]
        assert lookup(
            custom_client,
            {"index_id": "products", "query": "shoes", "min_examines": 4},
        ).json()["docs"] == []


def test_min_examines_is_read_from_the_environment(monkeypatch, db_path):
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("MIN_EXAMINES", "3")
    settings = Settings.from_env()

    with TestClient(create_app(settings)) as env_client:
        for _ in range(3):
            record(env_client)

        assert lookup(env_client, {"index_id": "products", "query": "shoes"}).json()[
            "docs"
        ] == [{"doc_id": "d1", "relevance": 1.0}]


# --- relevance math ---------------------------------------------------------


def test_relevance_is_three_successes_in_ten_examines(client):
    for _ in range(3):
        record(client)
    for _ in range(7):
        record(client, doc_ids=["d1", "d2"], clicked_doc_id="d2")

    response = lookup(client, {"index_id": "products", "query": "shoes", "min_examines": 10})

    assert response.json()["docs"] == [{"doc_id": "d1", "relevance": 0.3}]


def test_relevance_is_zero_when_never_clicked(client):
    record(client, doc_ids=["d1", "d2"], clicked_doc_id="d2")

    response = lookup(client, {"index_id": "products", "query": "shoes", "min_examines": 1})

    assert response.json()["docs"] == [
        {"doc_id": "d2", "relevance": 1.0},
        {"doc_id": "d1", "relevance": 0.0},
    ]


# --- normalization ----------------------------------------------------------


def test_different_spellings_of_a_query_hit_the_same_row(client):
    record(client, query="  Red   SHOE ")

    response = lookup(client, {"index_id": "products", "query": "red shoe", "min_examines": 1})

    assert response.status_code == 200
    assert response.json() == {
        "index_id": "products",
        "query": "red shoe",
        "docs": [{"doc_id": "d1", "relevance": 1.0}],
    }


def test_lookup_normalizes_the_query_in_the_response(client):
    record(client, query="  Red   SHOE ")

    response = lookup(
        client, {"index_id": "products", "query": "\tRed\n Shoe ", "min_examines": 1}
    )

    assert response.json()["query"] == "red shoe"
    assert response.json()["docs"] == [{"doc_id": "d1", "relevance": 1.0}]


def test_by_doc_reports_normalized_queries(client):
    record(client, query="  Red   SHOE ")

    response = lookup_doc(client, {"index_id": "products", "doc_id": "d1", "min_examines": 1})

    assert response.json()["queries"] == [{"query": "red shoe", "relevance": 1.0}]


# --- ordering ---------------------------------------------------------------


def test_by_query_ordering_is_deterministic(client):
    for _ in range(3):
        record(client, doc_ids=["d1"], clicked_doc_id="d1")  # d1: 3/3 = 1.0
    record(client, doc_ids=["d2"], clicked_doc_id="d2")
    record(client, doc_ids=["d2", "dz"], clicked_doc_id="dz")  # d2: 1/2 = 0.5
    record(client, doc_ids=["d3"], clicked_doc_id="d3")
    record(client, doc_ids=["d3", "dz"], clicked_doc_id="dz")  # d3: 1/2 = 0.5

    body = {"index_id": "products", "query": "shoes", "min_examines": 1}
    docs = lookup(client, body).json()["docs"]

    # d1: 3/3 = 1.0 with 3 examines, dz: 2/2 = 1.0 with 2 examines,
    # d2 / d3: 1/2 = 0.5 each (tie broken by doc_id ASC)
    assert docs == [
        {"doc_id": "d1", "relevance": 1.0},
        {"doc_id": "dz", "relevance": 1.0},
        {"doc_id": "d2", "relevance": 0.5},
        {"doc_id": "d3", "relevance": 0.5},
    ]
    assert lookup(client, body).json()["docs"] == docs


def test_by_doc_ordering_is_deterministic(client):
    record(client, query="q2", doc_ids=["d1"], clicked_doc_id="d1")
    record(client, query="q3", doc_ids=["d1"], clicked_doc_id="d1")
    record(client, query="q1", doc_ids=["d1"], clicked_doc_id="d1")
    record(client, query="q1", doc_ids=["d1", "dx"], clicked_doc_id="dx")  # q1: 1/2 = 0.5

    response = lookup_doc(client, {"index_id": "products", "doc_id": "d1", "min_examines": 1})

    # relevance DESC, then num_examines DESC, then query ASC
    assert response.json()["queries"] == [
        {"query": "q2", "relevance": 1.0},
        {"query": "q3", "relevance": 1.0},
        {"query": "q1", "relevance": 0.5},
    ]


# --- isolation --------------------------------------------------------------


def test_same_query_in_two_indexes_stays_separate(client):
    record(client, index_id="products", doc_ids=["d1"], clicked_doc_id="d1")
    record(client, index_id="articles", doc_ids=["d1", "d2"], clicked_doc_id="d2")

    products = lookup(
        client, {"index_id": "products", "query": "shoes", "min_examines": 1}
    ).json()
    articles = lookup(
        client, {"index_id": "articles", "query": "shoes", "min_examines": 1}
    ).json()

    assert products["docs"] == [{"doc_id": "d1", "relevance": 1.0}]
    assert articles["docs"] == [
        {"doc_id": "d2", "relevance": 1.0},
        {"doc_id": "d1", "relevance": 0.0},
    ]


def test_same_doc_in_two_indexes_stays_separate(client):
    record(client, index_id="products", doc_ids=["d1"], clicked_doc_id="d1")
    record(client, index_id="articles", doc_ids=["d1", "d2"], clicked_doc_id="d2")

    products = lookup_doc(
        client, {"index_id": "products", "doc_id": "d1", "min_examines": 1}
    ).json()
    articles = lookup_doc(
        client, {"index_id": "articles", "doc_id": "d1", "min_examines": 1}
    ).json()

    assert products["queries"] == [{"query": "shoes", "relevance": 1.0}]
    assert articles["queries"] == [{"query": "shoes", "relevance": 0.0}]


# --- persistence ------------------------------------------------------------


def test_data_survives_a_new_app_on_the_same_db_file(make_app):
    with TestClient(make_app()) as first_client:
        record(first_client, doc_ids=["d1", "d2"], clicked_doc_id="d2")

    with TestClient(make_app()) as second_client:
        response = lookup(
            second_client, {"index_id": "products", "query": "shoes", "min_examines": 1}
        )

    assert response.json()["docs"] == [
        {"doc_id": "d2", "relevance": 1.0},
        {"doc_id": "d1", "relevance": 0.0},
    ]


# --- validation -------------------------------------------------------------


INVALID_QUERY_LOOKUPS = [
    {"index_id": "products", "query": "shoes", "min_examines": 0},
    {"index_id": "products", "query": "shoes", "min_examines": -1},
    {"index_id": "products", "query": "shoes", "min_examines": "5"},
    {"index_id": "products", "query": "shoes", "min_examines": 5.0},
    {"index_id": "products", "query": "   "},
    {"index_id": "products", "query": 7},
    {"index_id": "", "query": "shoes"},
    {"query": "shoes"},
]


@pytest.mark.parametrize("payload", INVALID_QUERY_LOOKUPS)
def test_by_query_rejects_invalid_input(client, payload):
    response = lookup(client, payload)

    assert response.status_code == 422


INVALID_DOC_LOOKUPS = [
    {"index_id": "products", "doc_id": 7},
    {"index_id": "products", "doc_id": ""},
    {"index_id": "products", "doc_id": "d1", "min_examines": 0},
    {"index_id": "products", "doc_id": "d1", "min_examines": "3"},
    {"index_id": "products", "doc_id": "d1", "min_examines": 2.5},
    {"index_id": "products", "doc_id": "x" * 513},
    {"doc_id": "d1"},
]


@pytest.mark.parametrize("payload", INVALID_DOC_LOOKUPS)
def test_by_doc_rejects_invalid_input(client, payload):
    response = lookup_doc(client, payload)

    assert response.status_code == 422


# --- batch lookups ----------------------------------------------------------


def test_by_query_batch_returns_per_item_results_and_errors(client):
    record(client)

    response = client.post(
        "/v1/relevance/by-query/batch",
        json={
            "items": [
                {"index_id": "products", "query": "Shoes", "min_examines": 1},
                {"index_id": "products", "query": "   "},
                {"index_id": "products", "query": "shoes", "min_examines": 2},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "position": 0,
                "ok": True,
                "result": {
                    "index_id": "products",
                    "query": "shoes",
                    "docs": [{"doc_id": "d1", "relevance": 1.0}],
                },
            },
            {
                "position": 1,
                "ok": False,
                "error": "query: query must not be empty after normalization",
            },
            {
                "position": 2,
                "ok": True,
                "result": {"index_id": "products", "query": "shoes", "docs": []},
            },
        ]
    }


def test_by_doc_batch_returns_per_item_results_and_errors(client):
    record(client)

    response = client.post(
        "/v1/relevance/by-doc/batch",
        json={
            "items": [
                {"index_id": "products", "doc_id": "d1", "min_examines": 1},
                {"index_id": "products", "doc_id": ""},
                {"index_id": "products", "doc_id": "nope"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "position": 0,
            "ok": True,
            "result": {
                "index_id": "products",
                "doc_id": "d1",
                "queries": [{"query": "shoes", "relevance": 1.0}],
            },
        },
        {
            "position": 1,
            "ok": False,
            "error": "doc_id: String should have at least 1 character",
        },
        {
            "position": 2,
            "ok": True,
            "result": {"index_id": "products", "doc_id": "nope", "queries": []},
        },
    ]


def test_batch_lookup_items_may_carry_their_own_min_examines(client):
    for _ in range(3):
        record(client)

    response = client.post(
        "/v1/relevance/by-query/batch",
        json={
            "items": [
                {"index_id": "products", "query": "shoes", "min_examines": 3},
                {"index_id": "products", "query": "shoes", "min_examines": 4},
            ]
        },
    )

    results = response.json()["results"]
    assert results[0]["result"]["docs"] == [{"doc_id": "d1", "relevance": 1.0}]
    assert results[1]["result"]["docs"] == []


def test_batch_lookups_use_the_settings_default_when_omitted(client):
    for _ in range(9):
        record(client)

    response = client.post(
        "/v1/relevance/by-query/batch",
        json={"items": [{"index_id": "products", "query": "shoes"}]},
    )

    assert response.json()["results"][0]["result"]["docs"] == []


def test_by_query_batch_rejects_an_empty_items_list(client):
    response = client.post("/v1/relevance/by-query/batch", json={"items": []})

    assert response.status_code == 422


def test_by_doc_batch_rejects_too_many_items(make_app):
    with TestClient(make_app(max_batch_size=2)) as small_client:
        response = small_client.post(
            "/v1/relevance/by-doc/batch",
            json={"items": [{"index_id": "products", "doc_id": "d1"}] * 3},
        )

    assert response.status_code == 422


# --- min_examines upper bound (2**63 - 1) -----------------------------------


def test_by_query_rejects_min_examines_above_the_sqlite_integer_range(client):
    response = lookup(
        client, {"index_id": "products", "query": "shoes", "min_examines": 2**63}
    )

    assert response.status_code == 422


def test_by_query_batch_reports_an_out_of_range_min_examines_per_item(client):
    record(client)

    response = client.post(
        "/v1/relevance/by-query/batch",
        json={
            "items": [
                {"index_id": "products", "query": "shoes", "min_examines": 1},
                {"index_id": "products", "query": "shoes", "min_examines": 2**63},
                {"index_id": "products", "query": "shoes", "min_examines": 1},
            ]
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert [entry["ok"] for entry in results] == [True, False, True]
    assert results[1]["error"] == (
        "min_examines: Input should be less than or equal to 9223372036854775807"
    )
    # the items around it are unaffected
    assert results[0]["result"]["docs"] == [{"doc_id": "d1", "relevance": 1.0}]
    assert results[2]["result"]["docs"] == [{"doc_id": "d1", "relevance": 1.0}]
