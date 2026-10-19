"""All SQLite access for the relevance API.

Every method opens its own short-lived connection so that no connection is
ever shared across threads (FastAPI runs sync endpoints in a thread pool).
Connections are wrapped in ``contextlib.closing`` *and* ``with conn:`` so the
transaction is committed/rolled back and the file handle is always released
(important on Windows with WAL files).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS relevance_counts (
  index_id      TEXT NOT NULL,
  query         TEXT NOT NULL,
  doc_id        TEXT NOT NULL,
  num_examines  INTEGER NOT NULL DEFAULT 0 CHECK (num_examines >= 0),
  num_successes INTEGER NOT NULL DEFAULT 0
                CHECK (num_successes >= 0 AND num_successes <= num_examines),
  PRIMARY KEY (index_id, query, doc_id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_counts_index_doc
  ON relevance_counts (index_id, doc_id);
"""

# Run once per examined doc, with the last parameter = 1 for the clicked doc
# and 0 for the others.
UPSERT_EXAMINE = """
INSERT INTO relevance_counts (index_id, query, doc_id, num_examines, num_successes)
VALUES (?, ?, ?, 1, ?)
ON CONFLICT (index_id, query, doc_id) DO UPDATE SET
  num_examines  = num_examines + 1,
  num_successes = num_successes + excluded.num_successes;
"""

SELECT_BY_QUERY = """
SELECT doc_id, num_successes, num_examines
FROM relevance_counts
WHERE index_id = ? AND query = ? AND num_examines >= ?
"""

SELECT_BY_DOC = """
SELECT query, num_successes, num_examines
FROM relevance_counts
WHERE index_id = ? AND doc_id = ? AND num_examines >= ?
"""

#: Rows are ``(identifier, num_successes, num_examines)``.
CountRow = tuple[str, int, int]


def _rank(row: CountRow) -> tuple[float, int, str]:
    """Sort key: relevance DESC, num_examines DESC, identifier ASC."""
    identifier, num_successes, num_examines = row
    return (-(num_successes / num_examines), -num_examines, identifier)


class Repository:
    """Storage for per-(index_id, query, doc_id) examine/success counters."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def init_schema(self) -> None:
        """Create the schema if needed (idempotent).

        ``journal_mode=WAL`` is set once here; it persists in the database
        file, so later connections inherit it.
        """
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                conn.executescript(SCHEMA)

    def record_interaction(
        self,
        index_id: str,
        query: str,
        doc_ids: Sequence[str],
        clicked_doc_id: str,
    ) -> int:
        """Apply one interaction. Returns the number of docs examined.

        Every doc from the top of the list through the clicked doc (inclusive)
        gets ``num_examines + 1``; only the clicked doc gets
        ``num_successes + 1``. All upserts run in a single transaction.
        """
        position = list(doc_ids).index(clicked_doc_id)
        rows = [
            (index_id, query, doc_id, 1 if doc_id == clicked_doc_id else 0)
            for doc_id in doc_ids[: position + 1]
        ]
        with closing(self._connect()) as conn:
            with conn:
                conn.executemany(UPSERT_EXAMINE, rows)
        return position + 1

    def lookup_by_query(
        self, index_id: str, query: str, min_examines: int
    ) -> list[CountRow]:
        """Return ``(doc_id, num_successes, num_examines)`` rows for a query."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                SELECT_BY_QUERY, (index_id, query, min_examines)
            ).fetchall()
        return sorted((tuple(row) for row in rows), key=_rank)

    def lookup_by_doc(
        self, index_id: str, doc_id: str, min_examines: int
    ) -> list[CountRow]:
        """Return ``(query, num_successes, num_examines)`` rows for a doc."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                SELECT_BY_DOC, (index_id, doc_id, min_examines)
            ).fetchall()
        return sorted((tuple(row) for row in rows), key=_rank)
