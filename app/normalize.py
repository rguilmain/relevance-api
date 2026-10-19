"""Query normalization.

A single canonical form is used for both writing interactions and reading
relevance counts, so that ``"  Red   SHOE "`` and ``"red shoe"`` refer to the
same stored row.
"""

from __future__ import annotations


def normalize_query(query: str) -> str:
    """Return ``query`` trimmed, lowercased and whitespace-collapsed.

    Whitespace-only input normalizes to the empty string.
    """
    return " ".join(query.lower().split())
