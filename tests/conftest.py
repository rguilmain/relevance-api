"""Shared pytest fixtures.

Every test app uses its own temporary SQLite file via ``tmp_path``, and every
test runs from a throwaway working directory so nothing is written into the
project root.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path_factory, monkeypatch):
    """Run each test from a temporary directory, not the project directory."""
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "relevance.db")


@pytest.fixture
def settings(db_path):
    return Settings(db_path=db_path, min_examines=10, max_batch_size=1000)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_app(db_path):
    """Factory for apps with custom settings on the same temp database."""

    def _make_app(min_examines=10, max_batch_size=1000):
        settings = Settings(
            db_path=db_path,
            min_examines=min_examines,
            max_batch_size=max_batch_size,
        )
        return create_app(settings)

    return _make_app
