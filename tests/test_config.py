import os
from dataclasses import FrozenInstanceError

import pytest

from app.config import (
    DEFAULT_DB_PATH,
    DEFAULT_MAX_BATCH_SIZE,
    DEFAULT_MIN_EXAMINES,
    Settings,
)


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings.from_env({})
    assert settings.min_examines == DEFAULT_MIN_EXAMINES == 10
    assert settings.max_batch_size == DEFAULT_MAX_BATCH_SIZE == 1000
    assert settings.db_path == DEFAULT_DB_PATH


def test_reads_env_values():
    settings = Settings.from_env(
        {"DB_PATH": "some/path.db", "MIN_EXAMINES": "3", "MAX_BATCH_SIZE": "7"}
    )
    assert settings.min_examines == 3
    assert settings.max_batch_size == 7
    assert settings.db_path == "some/path.db"


def test_creates_parent_directory(tmp_path):
    target = tmp_path / "nested" / "dir" / "relevance.db"
    Settings.from_env({"DB_PATH": str(target)})
    assert target.parent.is_dir()


def test_reads_os_environ_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "env.db"))
    monkeypatch.setenv("MIN_EXAMINES", "5")
    monkeypatch.setenv("MAX_BATCH_SIZE", "42")
    settings = Settings.from_env()
    assert settings.db_path == str(tmp_path / "env.db")
    assert settings.min_examines == 5
    assert settings.max_batch_size == 42


@pytest.mark.parametrize("value", ["0", "-1", "abc", "", "1.5", "  ", "1e3"])
def test_invalid_min_examines_fails_fast(value):
    with pytest.raises(ValueError, match="MIN_EXAMINES must be an integer >= 1"):
        Settings.from_env({"MIN_EXAMINES": value})


@pytest.mark.parametrize("value", ["0", "-5", "nope", ""])
def test_invalid_max_batch_size_fails_fast(value):
    with pytest.raises(ValueError, match="MAX_BATCH_SIZE must be an integer >= 1"):
        Settings.from_env({"MAX_BATCH_SIZE": value})


def test_settings_is_frozen():
    settings = Settings(db_path="x.db", min_examines=1, max_batch_size=1)
    with pytest.raises(FrozenInstanceError):
        settings.min_examines = 2  # type: ignore[misc]


def test_error_message_mentions_variable_name():
    with pytest.raises(ValueError) as excinfo:
        Settings.from_env({"MIN_EXAMINES": "oops"})
    assert "MIN_EXAMINES" in str(excinfo.value)
    assert "oops" in str(excinfo.value)


def test_does_not_mutate_process_environ(tmp_path, monkeypatch):
    monkeypatch.delenv("DB_PATH", raising=False)
    Settings.from_env({"DB_PATH": str(tmp_path / "x.db")})
    assert "DB_PATH" not in os.environ


def test_min_examines_above_the_sqlite_integer_range_fails_fast():
    with pytest.raises(ValueError, match="MIN_EXAMINES"):
        Settings.from_env({"MIN_EXAMINES": "9223372036854775808"})


def test_min_examines_at_the_sqlite_integer_maximum_is_allowed():
    settings = Settings.from_env({"MIN_EXAMINES": "9223372036854775807"})

    assert settings.min_examines == 2**63 - 1
