import sqlite3
from contextlib import closing

import pytest

from app.repository import Repository


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "relevance.db")


@pytest.fixture
def repo(db_path):
    repository = Repository(db_path)
    repository.init_schema()
    return repository


def counts(rows):
    """Map identifier -> (num_successes, num_examines)."""
    return {
        identifier: (successes, examines)
        for identifier, successes, examines in rows
    }


def test_init_schema_is_idempotent(db_path):
    repository = Repository(db_path)
    repository.init_schema()
    repository.init_schema()


def test_init_sets_wal_journal_mode(db_path):
    Repository(db_path).init_schema()
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_successes_cannot_exceed_examines(db_path):
    repository = Repository(db_path)
    repository.init_schema()
    with closing(sqlite3.connect(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            with conn:
                conn.execute(
                    "INSERT INTO relevance_counts"
                    " (index_id, query, doc_id, num_examines, num_successes)"
                    " VALUES (?, ?, ?, ?, ?)",
                    ("i", "q", "d", 1, 2),
                )


def test_click_on_first_position_examines_only_one_doc(repo):
    examined = repo.record_interaction("products", "shoes", ["d1", "d2", "d3"], "d1")

    assert examined == 1
    assert counts(repo.lookup_by_query("products", "shoes", 1)) == {"d1": (1, 1)}


def test_click_on_last_position_examines_all_docs(repo):
    examined = repo.record_interaction("products", "shoes", ["d1", "d2", "d3"], "d3")

    assert examined == 3
    assert counts(repo.lookup_by_query("products", "shoes", 1)) == {
        "d1": (0, 1),
        "d2": (0, 1),
        "d3": (1, 1),
    }


def test_docs_below_the_click_are_untouched(repo):
    repo.record_interaction("products", "shoes", ["d1", "d2", "d3", "d4"], "d2")

    assert counts(repo.lookup_by_query("products", "shoes", 1)) == {
        "d1": (0, 1),
        "d2": (1, 1),
    }


def test_only_clicked_doc_gets_successes(repo):
    repo.record_interaction("products", "shoes", ["d1", "d2", "d3"], "d3")

    by_doc = counts(repo.lookup_by_query("products", "shoes", 1))
    assert by_doc["d3"][0] == 1
    assert by_doc["d1"][0] == 0
    assert by_doc["d2"][0] == 0


def test_counts_accumulate_across_interactions(repo):
    repo.record_interaction("products", "shoes", ["d1", "d2"], "d2")
    repo.record_interaction("products", "shoes", ["d2", "d1"], "d1")

    assert counts(repo.lookup_by_query("products", "shoes", 1)) == {
        "d1": (1, 2),
        "d2": (1, 2),
    }


def test_clicked_doc_must_be_in_doc_ids(repo):
    with pytest.raises(ValueError):
        repo.record_interaction("products", "shoes", ["d1"], "missing")


def test_relevance_math_three_successes_in_ten_examines(repo):
    for _ in range(3):
        repo.record_interaction("products", "shoes", ["target"], "target")
    for _ in range(7):
        repo.record_interaction("products", "shoes", ["target", "other"], "other")

    rows = counts(repo.lookup_by_query("products", "shoes", 1))
    successes, examines = rows["target"]
    assert (successes, examines) == (3, 10)
    assert successes / examines == pytest.approx(0.3)


def test_min_examines_hides_and_shows_a_triple(repo):
    for _ in range(9):
        repo.record_interaction("products", "shoes", ["d1"], "d1")

    assert repo.lookup_by_query("products", "shoes", 10) == []

    repo.record_interaction("products", "shoes", ["d1"], "d1")

    assert repo.lookup_by_query("products", "shoes", 10) == [("d1", 10, 10)]


def test_min_examines_one_shows_everything(repo):
    repo.record_interaction("products", "shoes", ["d1"], "d1")

    assert repo.lookup_by_query("products", "shoes", 1) == [("d1", 1, 1)]


def test_lookup_by_query_ordering_is_deterministic(repo):
    index_id, query = "products", "shoes"

    def interact(doc_ids, clicked):
        repo.record_interaction(index_id, query, doc_ids, clicked)

    # t1 / t2: 1 success in 6 examines each (equal -> doc_id ASC tie-break)
    interact(["t1"], "t1")
    interact(["t2"], "t2")
    for _ in range(5):
        interact(["t1", "zz"], "zz")
        interact(["t2", "zz"], "zz")
    # hi: 3 / 5 = 0.6
    for _ in range(3):
        interact(["hi"], "hi")
    for _ in range(2):
        interact(["hi", "zz"], "zz")
    # da: 2 / 4 = 0.5, db: 1 / 2 = 0.5 (equal relevance -> examines DESC)
    for _ in range(2):
        interact(["da"], "da")
    for _ in range(2):
        interact(["da", "zz"], "zz")
    interact(["db"], "db")
    interact(["db", "zz"], "zz")

    rows = repo.lookup_by_query(index_id, query, 1)

    assert counts(rows) == {
        "zz": (15, 15),
        "hi": (3, 5),
        "da": (2, 4),
        "db": (1, 2),
        "t1": (1, 6),
        "t2": (1, 6),
    }
    # relevance DESC, then num_examines DESC, then doc_id ASC
    assert [doc_id for doc_id, _, _ in rows] == ["zz", "hi", "da", "db", "t1", "t2"]


def test_lookup_by_doc_ordering_is_deterministic(repo):
    index_id, doc_id, other = "products", "d1", "d2"

    def interact(query, doc_ids, clicked):
        repo.record_interaction(index_id, query, doc_ids, clicked)

    # gamma: 1/1 = 1.0
    interact("gamma", [doc_id], doc_id)
    # epsilon: 2/4 = 0.5 with 4 examines
    for _ in range(2):
        interact("epsilon", [doc_id], doc_id)
    for _ in range(2):
        interact("epsilon", [doc_id, other], other)
    # alpha / beta: 1/2 = 0.5 with 2 examines
    interact("alpha", [doc_id], doc_id)
    interact("alpha", [doc_id, other], other)
    interact("beta", [doc_id], doc_id)
    interact("beta", [doc_id, other], other)
    # delta: 1/4 = 0.25
    interact("delta", [doc_id], doc_id)
    for _ in range(3):
        interact("delta", [doc_id, other], other)

    rows = repo.lookup_by_doc(index_id, doc_id, 1)

    assert counts(rows) == {
        "gamma": (1, 1),
        "epsilon": (2, 4),
        "alpha": (1, 2),
        "beta": (1, 2),
        "delta": (1, 4),
    }
    # relevance DESC, then num_examines DESC, then query ASC
    assert [query for query, _, _ in rows] == [
        "gamma",
        "epsilon",
        "alpha",
        "beta",
        "delta",
    ]


def test_min_examines_applies_to_by_doc_lookup(repo):
    for _ in range(3):
        repo.record_interaction("products", "shoes", ["d1"], "d1")

    assert repo.lookup_by_doc("products", "d1", 4) == []
    assert repo.lookup_by_doc("products", "d1", 3) == [("shoes", 3, 3)]


def test_index_id_isolation(repo):
    repo.record_interaction("products", "shoes", ["d1"], "d1")
    repo.record_interaction("articles", "shoes", ["d1", "d2"], "d2")

    assert repo.lookup_by_query("products", "shoes", 1) == [("d1", 1, 1)]
    assert counts(repo.lookup_by_query("articles", "shoes", 1)) == {
        "d1": (0, 1),
        "d2": (1, 1),
    }


def test_unknown_query_returns_empty_list(repo):
    assert repo.lookup_by_query("products", "nothing", 1) == []


def test_unknown_index_returns_empty_list(repo):
    repo.record_interaction("products", "shoes", ["d1"], "d1")

    assert repo.lookup_by_query("other", "shoes", 1) == []
    assert repo.lookup_by_doc("other", "d1", 1) == []


def test_lookup_by_doc_unknown_doc_returns_empty_list(repo):
    repo.record_interaction("products", "shoes", ["d1"], "d1")

    assert repo.lookup_by_doc("products", "d2", 1) == []
