from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import docxtool.storage.database as database


def test_database_path_prefers_environment_absolute(monkeypatch, tmp_path):
    db_path = tmp_path / "explicit" / "stats.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    assert Path(database.default_database_path()) == db_path
    assert not db_path.parent.exists()


def test_database_path_resolves_relative_environment_to_project(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "project_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setenv("DATABASE_PATH", "custom/stats.db")

    assert Path(database.default_database_path()) == tmp_path / "custom" / "stats.db"
    assert not (tmp_path / "custom").exists()


def test_database_path_uses_legacy_once(monkeypatch, tmp_path, capsys):
    legacy = tmp_path / "stats.db"
    legacy.write_bytes(b"legacy")
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.setattr(database, "_LEGACY_WARNING_EMITTED", False)
    monkeypatch.setattr(database, "project_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(database, "var_path", lambda *parts: tmp_path.joinpath("var", *parts))

    assert Path(database.default_database_path()) == legacy
    assert Path(database.default_database_path()) == legacy

    captured = capsys.readouterr()
    assert captured.err.count("LEGACY_DATABASE_PATH_USED") == 1


def test_database_path_defaults_to_var_without_creating_parent(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.setattr(database, "project_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(database, "var_path", lambda *parts: tmp_path.joinpath("var", *parts))

    assert Path(database.default_database_path()) == tmp_path / "var" / "data" / "stats.db"
    assert not (tmp_path / "var").exists()


def test_connect_creates_parent_and_returns_independent_row_connections(tmp_path):
    db_path = tmp_path / "nested" / "stats.db"

    first = database.connect(db_path)
    second = database.connect(db_path)
    try:
        assert first is not second
        assert first.row_factory is sqlite3.Row
        assert second.row_factory is sqlite3.Row
        assert first.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert db_path.exists()
    finally:
        first.close()
        second.close()


def test_import_has_no_database_side_effect(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "stats.db"))

    importlib.reload(database)

    assert not (tmp_path / "stats.db").exists()
