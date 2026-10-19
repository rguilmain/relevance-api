"""Concurrency: 8 threads x 25 interactions must produce exact final counts."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.repository import Repository

THREADS = 8
INTERACTIONS_PER_THREAD = 25
TOTAL = THREADS * INTERACTIONS_PER_THREAD


@pytest.fixture
def repo(tmp_path):
    repository = Repository(str(tmp_path / "relevance.db"))
    repository.init_schema()
    return repository


def test_concurrent_interactions_produce_exact_counts(repo):
    index_id, query, doc_ids = "products", "shoes", ["a", "b", "c"]

    def worker(_):
        for _ in range(INTERACTIONS_PER_THREAD):
            repo.record_interaction(index_id, query, doc_ids, "b")

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        list(pool.map(worker, range(THREADS)))

    rows = repo.lookup_by_query(index_id, query, 1)
    counts = {doc_id: (successes, examines) for doc_id, successes, examines in rows}

    assert counts == {"a": (0, TOTAL), "b": (TOTAL, TOTAL)}
    # "c" sits below the clicked doc and must never be written
    assert "c" not in counts

    # every interaction is accounted for: a cutoff of TOTAL still shows both
    assert repo.lookup_by_query(index_id, query, TOTAL) == [
        ("b", TOTAL, TOTAL),
        ("a", 0, TOTAL),
    ]
    assert repo.lookup_by_query(index_id, query, TOTAL + 1) == []


def test_concurrent_interactions_across_queries_do_not_lose_updates(repo):
    index_id = "products"
    threads_per_query = THREADS // 4
    per_query = threads_per_query * INTERACTIONS_PER_THREAD

    def worker(thread_index):
        query = "query-%d" % (thread_index % 4)
        for _ in range(INTERACTIONS_PER_THREAD):
            repo.record_interaction(index_id, query, ["shared"], "shared")

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        list(pool.map(worker, range(THREADS)))

    for query_index in range(4):
        query = "query-%d" % query_index
        assert repo.lookup_by_query(index_id, query, 1) == [
            ("shared", per_query, per_query)
        ]
        assert repo.lookup_by_query(index_id, query, per_query + 1) == []
