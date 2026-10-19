"""Application settings, read from environment variables.

Environment variables:

==================  ======================  ==========================
Variable            Default                 Rule
==================  ======================  ==========================
``DB_PATH``         ``./data/relevance.db`` create parent dir if missing
``MIN_EXAMINES``    ``10``                  integer >= 1
``MAX_BATCH_SIZE``  ``1000``                integer >= 1
==================  ======================  ==========================

Invalid values fail fast at startup with a clear error message.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

DEFAULT_DB_PATH = "./data/relevance.db"
DEFAULT_MIN_EXAMINES = 10
DEFAULT_MAX_BATCH_SIZE = 1000

#: Largest value a SQLite INTEGER (signed 64-bit) can hold. ``MIN_EXAMINES``
#: above this would never be comparable to the stored counters.
MAX_MIN_EXAMINES = 2**63 - 1


def _int_env(
    env: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    """Parse ``env[name]`` as an integer within bounds, or raise ``ValueError``."""
    raw = env.get(name)
    if raw is None:
        return default
    expected = f"an integer >= {minimum}"
    if maximum is not None:
        expected = f"an integer >= {minimum} and <= {maximum}"
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be {expected}, got {raw!r}") from None
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be {expected}, got {raw!r}")
    return value


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the application."""

    db_path: str
    min_examines: int
    max_batch_size: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build settings from ``env`` (defaults to ``os.environ``).

        Creates the database parent directory when missing. Raises
        ``ValueError`` for invalid integer values.
        """
        source = os.environ if env is None else env
        db_path = str(source.get("DB_PATH", DEFAULT_DB_PATH))
        min_examines = _int_env(
            source, "MIN_EXAMINES", DEFAULT_MIN_EXAMINES, 1, MAX_MIN_EXAMINES
        )
        max_batch_size = _int_env(source, "MAX_BATCH_SIZE", DEFAULT_MAX_BATCH_SIZE, 1)

        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

        return cls(
            db_path=db_path,
            min_examines=min_examines,
            max_batch_size=max_batch_size,
        )
