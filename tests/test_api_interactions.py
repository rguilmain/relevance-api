from fastapi.testclient import TestClient

import pytest


def interaction(index_id="i", query="q", doc_ids=("a",), clicked_doc_id="a"):
    return {
        "index_id": index_id,
        "query": query,
        "doc_ids": list(doc_ids),
        "clicked_doc_id": clicked_doc_id,
    }


# --- health -----------------------------------------------------------------


def test_healthz(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- single interaction -----------------------------------------------------


def test_single_interaction_returns_examined_count_and_normalized_query(client):
    response = client.post(
        "/v1/interactions",
        json={
            "index_id": "products",
            "query": "  Red   Shoes ",
            "doc_ids": ["d1", "d2", "d3", "d4"],
            "clicked_doc_id": "d3",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "index_id": "products",
        "query": "red shoes",
        "docs_examined": 3,
    }


def test_click_on_the_first_position_examines_one_doc(client):
    response = client.post(
        "/v1/interactions",
        json=interaction(doc_ids=["a", "b", "c"], clicked_doc_id="a"),
    )

    assert response.status_code == 200
    assert response.json()["docs_examined"] == 1


def test_click_on_the_last_position_examines_all_docs(client):
    response = client.post(
        "/v1/interactions",
        json=interaction(doc_ids=["a", "b", "c"], clicked_doc_id="c"),
    )

    assert response.status_code == 200
    assert response.json()["docs_examined"] == 3


def test_docs_below_the_click_are_untouched(client):
    client.post(
        "/v1/interactions",
        json=interaction(doc_ids=["d1", "d2", "d3", "d4"], clicked_doc_id="d2"),
    )

    response = client.post(
        "/v1/relevance/by-query",
        json={"index_id": "i", "query": "q", "min_examines": 1},
    )

    assert [doc["doc_id"] for doc in response.json()["docs"]] == ["d2", "d1"]


def test_only_the_clicked_doc_gets_a_success(client):
    client.post(
        "/v1/interactions",
        json=interaction(doc_ids=["d1", "d2", "d3"], clicked_doc_id="d3"),
    )

    response = client.post(
        "/v1/relevance/by-query",
        json={"index_id": "i", "query": "q", "min_examines": 1},
    )

    assert response.json()["docs"] == [
        {"doc_id": "d3", "relevance": 1.0},
        {"doc_id": "d1", "relevance": 0.0},
        {"doc_id": "d2", "relevance": 0.0},
    ]


INVALID_INTERACTIONS = [
    (
        "clicked_doc_id not in doc_ids",
        {"index_id": "i", "query": "q", "doc_ids": ["a"], "clicked_doc_id": "b"},
    ),
    (
        "duplicate doc_ids",
        {"index_id": "i", "query": "q", "doc_ids": ["a", "a"], "clicked_doc_id": "a"},
    ),
    (
        "empty doc_ids",
        {"index_id": "i", "query": "q", "doc_ids": [], "clicked_doc_id": "a"},
    ),
    (
        "doc_ids is a string",
        {"index_id": "i", "query": "q", "doc_ids": "a", "clicked_doc_id": "a"},
    ),
    (
        "non-string index_id",
        {"index_id": 7, "query": "q", "doc_ids": ["a"], "clicked_doc_id": "a"},
    ),
    (
        "non-string doc id",
        {"index_id": "i", "query": "q", "doc_ids": ["a", 7], "clicked_doc_id": "a"},
    ),
    (
        "non-string clicked_doc_id",
        {"index_id": "i", "query": "q", "doc_ids": ["a"], "clicked_doc_id": 7},
    ),
    (
        "non-string query",
        {"index_id": "i", "query": 7, "doc_ids": ["a"], "clicked_doc_id": "a"},
    ),
    (
        "empty index_id",
        {"index_id": "", "query": "q", "doc_ids": ["a"], "clicked_doc_id": "a"},
    ),
    (
        "index_id too long",
        {"index_id": "x" * 513, "query": "q", "doc_ids": ["a"], "clicked_doc_id": "a"},
    ),
    (
        "doc id too long",
        {
            "index_id": "i",
            "query": "q",
            "doc_ids": ["y" * 513],
            "clicked_doc_id": "y" * 513,
        },
    ),
    (
        "whitespace-only query",
        {"index_id": "i", "query": "   \t\n ", "doc_ids": ["a"], "clicked_doc_id": "a"},
    ),
    (
        "query too long after normalization",
        {"index_id": "i", "query": "x" * 513, "doc_ids": ["a"], "clicked_doc_id": "a"},
    ),
    (
        "missing doc_ids",
        {"index_id": "i", "query": "q", "clicked_doc_id": "a"},
    ),
]


@pytest.mark.parametrize(
    "payload", [payload for _, payload in INVALID_INTERACTIONS], ids=[name for name, _ in INVALID_INTERACTIONS]
)
def test_single_interaction_rejects_invalid_input(client, payload):
    response = client.post("/v1/interactions", json=payload)

    assert response.status_code == 422


def test_query_length_is_checked_after_normalization(client):
    raw_query = "  " + "\t" * 40 + "x" * 512 + "\n" * 20
    assert len(raw_query) > 512

    response = client.post(
        "/v1/interactions",
        json={
            "index_id": "i",
            "query": raw_query,
            "doc_ids": ["a"],
            "clicked_doc_id": "a",
        },
    )

    assert response.status_code == 200
    assert len(response.json()["query"]) == 512


# --- batch interactions -----------------------------------------------------


def test_batch_applies_valid_items_and_reports_invalid_ones(client):
    response = client.post(
        "/v1/interactions/batch",
        json={
            "items": [
                {
                    "index_id": "products",
                    "query": "  Red   Shoes ",
                    "doc_ids": ["d1", "d2", "d3", "d4"],
                    "clicked_doc_id": "d3",
                },
                {
                    "index_id": "products",
                    "query": "red shoes",
                    "doc_ids": ["d1"],
                    "clicked_doc_id": "missing",
                },
                {
                    "index_id": "products",
                    "query": "red shoes",
                    "doc_ids": ["d1"],
                    "clicked_doc_id": "d1",
                },
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
                    "query": "red shoes",
                    "docs_examined": 3,
                },
            },
            {
                "position": 1,
                "ok": False,
                "error": "clicked_doc_id: clicked_doc_id must be in doc_ids",
            },
            {
                "position": 2,
                "ok": True,
                "result": {
                    "index_id": "products",
                    "query": "red shoes",
                    "docs_examined": 1,
                },
            },
        ]
    }


def test_batch_applies_the_valid_items_of_a_mixed_batch(client):
    client.post(
        "/v1/interactions/batch",
        json={
            "items": [
                {
                    "index_id": "products",
                    "query": "red shoes",
                    "doc_ids": ["d1", "d2", "d3"],
                    "clicked_doc_id": "d3",
                },
                {"index_id": "products", "query": "red shoes", "doc_ids": []},
                {
                    "index_id": "products",
                    "query": "red shoes",
                    "doc_ids": ["d1"],
                    "clicked_doc_id": "d1",
                },
            ]
        },
    )

    response = client.post(
        "/v1/relevance/by-query",
        json={"index_id": "products", "query": "red shoes", "min_examines": 1},
    )

    assert response.json()["docs"] == [
        {"doc_id": "d3", "relevance": 1.0},
        {"doc_id": "d1", "relevance": 0.5},
        {"doc_id": "d2", "relevance": 0.0},
    ]


def test_batch_reports_a_non_dict_item_without_failing(client):
    response = client.post(
        "/v1/interactions/batch",
        json={"items": [interaction(), "not-an-object", interaction()]},
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert [entry["position"] for entry in results] == [0, 1, 2]
    assert [entry["ok"] for entry in results] == [True, False, True]
    assert "Input should be a valid dictionary" in results[1]["error"]


def test_batch_counts_a_duplicate_triple_twice(client):
    item = interaction(doc_ids=["d1"], clicked_doc_id="d1")
    response = client.post("/v1/interactions/batch", json={"items": [item, item]})

    assert response.status_code == 200
    assert [entry["ok"] for entry in response.json()["results"]] == [True, True]

    shown = client.post(
        "/v1/relevance/by-query",
        json={"index_id": "i", "query": "q", "min_examines": 2},
    ).json()
    assert shown["docs"] == [{"doc_id": "d1", "relevance": 1.0}]

    hidden = client.post(
        "/v1/relevance/by-query",
        json={"index_id": "i", "query": "q", "min_examines": 3},
    ).json()
    assert hidden["docs"] == []


def test_batch_rejects_an_empty_items_list(client):
    response = client.post("/v1/interactions/batch", json={"items": []})

    assert response.status_code == 422


def test_batch_rejects_more_than_max_batch_size(make_app):
    with TestClient(make_app(max_batch_size=3)) as small_client:
        response = small_client.post(
            "/v1/interactions/batch",
            json={"items": [interaction() for _ in range(4)]},
        )

    assert response.status_code == 422


def test_batch_accepts_exactly_max_batch_size(make_app):
    with TestClient(make_app(max_batch_size=3)) as small_client:
        response = small_client.post(
            "/v1/interactions/batch",
            json={"items": [interaction() for _ in range(3)]},
        )

    assert response.status_code == 200
    assert len(response.json()["results"]) == 3


def test_batch_items_must_be_a_list(client):
    response = client.post("/v1/interactions/batch", json={"items": "not-a-list"})

    assert response.status_code == 422


def test_batch_requires_an_items_key(client):
    response = client.post("/v1/interactions/batch", json={})

    assert response.status_code == 422


# --- unknown fields are rejected (extra="forbid") ---------------------------


def test_single_interaction_rejects_unknown_fields(client):
    response = client.post(
        "/v1/interactions", json={**interaction(), "unknown_field": 1}
    )

    assert response.status_code == 422
    assert "unknown_field" in response.text


def test_batch_reports_unknown_fields_per_item_and_applies_the_rest(client):
    response = client.post(
        "/v1/interactions/batch",
        json={
            "items": [
                interaction(doc_ids=["d1"], clicked_doc_id="d1"),
                {
                    **interaction(doc_ids=["d2"], clicked_doc_id="d2"),
                    "unknown_field": 1,
                },
                interaction(doc_ids=["d3"], clicked_doc_id="d3"),
            ]
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert [entry["ok"] for entry in results] == [True, False, True]
    assert results[1]["error"] == "unknown_field: Extra inputs are not permitted"

    # the valid items were applied, the invalid one was not
    shown = client.post(
        "/v1/relevance/by-query",
        json={"index_id": "i", "query": "q", "min_examines": 1},
    ).json()
    assert [doc["doc_id"] for doc in shown["docs"]] == ["d1", "d3"]
