from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from docxtool.storage import database


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_SCRIPT = REPO_ROOT / "scripts" / "migrate_legacy_database.ps1"


@pytest.fixture(autouse=True)
def reset_database_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.setattr(database, "_LEGACY_WARNING_EMITTED", False)


@pytest.fixture
def repo_temp_dir() -> Iterator[Path]:
    parent = REPO_ROOT / "var" / "data"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pytest-db-", dir=parent, ignore_cleanup_errors=True) as raw_path:
        yield Path(raw_path)


def configure_project_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    def fake_project_path(*parts: str) -> Path:
        return root.joinpath(*parts)

    def fake_var_path(*parts: str) -> Path:
        return root.joinpath("var", *parts)

    monkeypatch.setattr(database, "project_path", fake_project_path)
    monkeypatch.setattr(database, "var_path", fake_var_path)


def create_sqlite_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO sample (value) VALUES ('ok')")


def sqlite_integrity(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]


def test_importing_database_module_does_not_create_database_or_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "missing-parent" / "stats.db"
    monkeypatch.setenv("DATABASE_PATH", str(target))

    import docxtool.storage.database as database_module

    importlib.reload(database_module)

    assert not target.parent.exists()
    assert not target.exists()


def test_database_path_prefers_environment_and_resolves_relative_to_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "project"
    configure_project_root(monkeypatch, root)
    (root / "stats.db").parent.mkdir(parents=True)
    (root / "stats.db").write_bytes(b"legacy")
    monkeypatch.setenv("DATABASE_PATH", "custom/stats.db")

    path = Path(database.default_database_path())

    assert path == root / "custom" / "stats.db"
    assert not path.parent.exists()
    assert capsys.readouterr().err == ""


def test_database_path_accepts_absolute_environment_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    absolute_path = tmp_path / "absolute" / "stats.db"
    monkeypatch.setenv("DATABASE_PATH", str(absolute_path))

    path = Path(database.default_database_path())

    assert path == absolute_path
    assert not absolute_path.parent.exists()


def test_database_path_uses_legacy_database_with_one_warning_per_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "project"
    configure_project_root(monkeypatch, root)
    legacy_path = root / "stats.db"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"legacy")

    first_path = Path(database.default_database_path())
    second_path = Path(database.default_database_path())
    stderr = capsys.readouterr().err

    assert first_path == legacy_path
    assert second_path == legacy_path
    assert stderr.count("LEGACY_DATABASE_PATH_USED") == 1


def test_database_path_defaults_to_var_data_without_creating_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    configure_project_root(monkeypatch, root)

    path = Path(database.default_database_path())

    assert path == root / "var" / "data" / "stats.db"
    assert not root.exists()


def test_connect_creates_parent_on_first_connection_and_database_is_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    configure_project_root(monkeypatch, root)
    db_path = root / "var" / "data" / "stats.db"

    assert not db_path.parent.exists()
    conn = database.connect()
    try:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    finally:
        conn.close()

    assert db_path.parent.exists()
    assert db_path.exists()
    assert sqlite_integrity(db_path) == "ok"


def test_connect_returns_independent_connections_with_row_factory(tmp_path: Path) -> None:
    db_path = tmp_path / "connections" / "stats.db"

    conn1 = database.connect(db_path)
    conn2 = database.connect(db_path)
    try:
        assert conn1 is not conn2
        conn1.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn1.execute("INSERT INTO sample (value) VALUES ('row-factory')")
        conn1.commit()

        row = conn2.execute("SELECT value FROM sample").fetchone()
        assert isinstance(row, sqlite3.Row)
        assert row["value"] == "row-factory"
    finally:
        conn1.close()
        conn2.close()


def run_migration_script(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(MIGRATION_SCRIPT), *args],
        cwd=REPO_ROOT,
        encoding="utf-8",
        errors="replace",
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_migration_script_dry_run_does_not_copy_database(tmp_path: Path) -> None:
    source = tmp_path / "source" / "stats.db"
    destination = tmp_path / "destination" / "stats.db"
    create_sqlite_database(source)

    result = run_migration_script("-Source", str(source), "-Destination", str(destination))

    assert result.returncode == 0, result.stderr
    assert "Dry run complete" in result.stdout
    assert sqlite_integrity(source) == "ok"
    assert not destination.exists()
    assert not destination.parent.exists()


def test_migration_script_execute_copies_and_validates_without_deleting_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source" / "stats.db"
    destination = tmp_path / "destination" / "stats.db"
    create_sqlite_database(source)

    result = run_migration_script(
        "-Execute",
        "-Source",
        str(source),
        "-Destination",
        str(destination),
    )

    assert result.returncode == 0, result.stderr
    assert "Destination integrity: ok" in result.stdout
    assert source.exists()
    assert destination.exists()
    assert not list(source.parent.glob("stats.db.backup-*"))
    assert sqlite_integrity(source) == "ok"
    assert sqlite_integrity(destination) == "ok"


def test_migration_script_execute_refuses_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source" / "stats.db"
    destination = tmp_path / "destination" / "stats.db"
    create_sqlite_database(source)
    create_sqlite_database(destination)

    result = run_migration_script(
        "-Execute",
        "-Source",
        str(source),
        "-Destination",
        str(destination),
    )

    assert result.returncode != 0
    assert "Destination already exists" in result.stderr
    assert source.exists()
    assert sqlite_integrity(source) == "ok"
    assert sqlite_integrity(destination) == "ok"
