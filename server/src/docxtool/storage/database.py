"""SQLite database path and connection helpers."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from docxtool.paths import project_path, var_path

_LEGACY_WARNING_EMITTED = False


def _warn_legacy_database(path: Path) -> None:
    global _LEGACY_WARNING_EMITTED
    if _LEGACY_WARNING_EMITTED:
        return
    _LEGACY_WARNING_EMITTED = True
    sys.stderr.write(
        "LEGACY_DATABASE_PATH_USED: using legacy stats.db. "
        "Stop the service and migrate to var/data/stats.db, or set DATABASE_PATH explicitly.\n"
    )


def _resolve_database_path(path: str | os.PathLike[str]) -> Path:
    """Resolve database paths relative to the project root."""
    db_path = Path(path)
    if db_path.is_absolute():
        return db_path
    return project_path(str(db_path))


def default_database_path() -> str:
    configured = os.environ.get("DATABASE_PATH")
    if configured:
        path = _resolve_database_path(configured)
    else:
        legacy_path = project_path("stats.db")
        if legacy_path.exists():
            _warn_legacy_database(legacy_path)
            path = legacy_path
        else:
            path = var_path("data", "stats.db")
    return str(path)


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    db_path = _resolve_database_path(path) if path is not None else Path(default_database_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
