"""Account-scoped local WPS format profiles backed by SQLite."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from typing import Iterator

from docxtool.document.configuration.validation import validate_format_config
from docxtool.document.errors import ConfigValidationError


MAX_PROFILE_NAME_CHARS = 80
MAX_PROFILE_CONFIG_BYTES = 64 * 1024


class FormatProfileError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def format_profile_database_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        raise FormatProfileError("WPS_FORMAT_PROFILE_DATABASE_FAILED")
    return Path(root) / "DocxTool" / "wps" / "format_profiles.db"


def _owner_id(value: str) -> str:
    owner = str(value or "").strip()
    if not owner:
        raise FormatProfileError("WPS_FORMAT_PROFILE_ACCOUNT_REQUIRED")
    return owner


def _profile_name(value: str) -> tuple[str, str]:
    name = re.sub(r"\s+", " ", str(value or "")).strip()
    if not name:
        raise FormatProfileError("WPS_FORMAT_PROFILE_NAME_REQUIRED")
    if len(name) > MAX_PROFILE_NAME_CHARS:
        raise FormatProfileError("WPS_FORMAT_PROFILE_NAME_TOO_LONG")
    return name, name.casefold()


def _profile_config(value: dict, *, migration: bool = False) -> tuple[str, int]:
    error_code = (
        "WPS_FORMAT_PROFILE_MIGRATION_FAILED"
        if migration
        else "WPS_FORMAT_PROFILE_CONFIG_INVALID"
    )
    try:
        normalized = validate_format_config(value)
    except (ConfigValidationError, TypeError, ValueError) as exc:
        raise FormatProfileError(error_code) from exc
    payload = json.dumps(
        normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if len(payload.encode("utf-8")) > MAX_PROFILE_CONFIG_BYTES:
        raise FormatProfileError(error_code)
    schema_version = normalized.get("schema_version", 1)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise FormatProfileError(error_code)
    return payload, schema_version


class FormatProfileStore:
    def __init__(self, database_path: Path | None = None, *, now_func=time.time) -> None:
        self.database_path = Path(database_path) if database_path else format_profile_database_path()
        self._now = now_func
        self._lock = threading.RLock()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = None
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.database_path))
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS format_profiles (
                    profile_id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(owner_user_id, name_key)
                );
                CREATE INDEX IF NOT EXISTS idx_format_profiles_owner_updated
                    ON format_profiles(owner_user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS format_profile_state (
                    owner_user_id TEXT PRIMARY KEY,
                    active_profile_id TEXT NOT NULL DEFAULT '',
                    legacy_migrated INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                );
                """
            )
            yield conn
        except FormatProfileError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise FormatProfileError("WPS_FORMAT_PROFILE_DATABASE_FAILED") from exc
        finally:
            if conn is not None:
                conn.close()

    def _now_int(self) -> int:
        return int(self._now())

    @staticmethod
    def _profile_from_row(row: sqlite3.Row) -> dict:
        try:
            config = validate_format_config(json.loads(row["config_json"]))
        except (TypeError, json.JSONDecodeError, ConfigValidationError) as exc:
            raise FormatProfileError("WPS_FORMAT_PROFILE_DATABASE_FAILED") from exc
        return {
            "profile_id": row["profile_id"],
            "name": row["name"],
            "is_system": False,
            "schema_version": int(row["schema_version"]),
            "revision": int(row["revision"]),
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
            "format_config": config,
        }

    @staticmethod
    def _metadata_from_row(row: sqlite3.Row) -> dict:
        return {
            "profile_id": row["profile_id"],
            "name": row["name"],
            "is_system": False,
            "schema_version": int(row["schema_version"]),
            "revision": int(row["revision"]),
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
        }

    def _ensure_state(self, conn: sqlite3.Connection, owner: str) -> sqlite3.Row:
        state = conn.execute(
            "SELECT * FROM format_profile_state WHERE owner_user_id=?", (owner,)
        ).fetchone()
        if state is not None:
            return state
        now = self._now_int()
        conn.execute(
            """INSERT INTO format_profile_state
               (owner_user_id, active_profile_id, legacy_migrated, updated_at)
               VALUES (?, '', 0, ?)""",
            (owner, now),
        )
        return conn.execute(
            "SELECT * FROM format_profile_state WHERE owner_user_id=?", (owner,)
        ).fetchone()

    @staticmethod
    def _owned_row(
        conn: sqlite3.Connection, owner: str, profile_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM format_profiles WHERE profile_id=? AND owner_user_id=?",
            (str(profile_id or ""), owner),
        ).fetchone()
        if row is None:
            raise FormatProfileError("WPS_FORMAT_PROFILE_NOT_FOUND")
        return row

    def initialize(self, owner_user_id: str, legacy_config: dict | None = None) -> dict:
        owner = _owner_id(owner_user_id)
        legacy_payload = None
        legacy_schema_version = 1
        if legacy_config is not None:
            legacy_payload, legacy_schema_version = _profile_config(
                legacy_config, migration=True
            )
        with self._lock, self._connection() as conn, conn:
            state = self._ensure_state(conn, owner)
            if bool(state["legacy_migrated"]):
                active = self._active_profile_with_connection(conn, owner, state)
                return {"legacy_imported": False, "active_profile": active}

            imported = False
            active_profile_id = str(state["active_profile_id"] or "")
            existing_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM format_profiles WHERE owner_user_id=?",
                    (owner,),
                ).fetchone()[0]
            )
            if legacy_payload is not None and existing_count == 0:
                profile_id = f"fmt_{secrets.token_hex(8)}"
                now = self._now_int()
                name, name_key = _profile_name("我的格式")
                conn.execute(
                    """INSERT INTO format_profiles
                       (profile_id, owner_user_id, name, name_key, config_json,
                        schema_version, revision, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        profile_id,
                        owner,
                        name,
                        name_key,
                        legacy_payload,
                        legacy_schema_version,
                        now,
                        now,
                    ),
                )
                active_profile_id = profile_id
                imported = True
            conn.execute(
                """UPDATE format_profile_state
                   SET active_profile_id=?, legacy_migrated=1, updated_at=?
                   WHERE owner_user_id=?""",
                (active_profile_id, self._now_int(), owner),
            )
            state = conn.execute(
                "SELECT * FROM format_profile_state WHERE owner_user_id=?", (owner,)
            ).fetchone()
            active = self._active_profile_with_connection(conn, owner, state)
            return {"legacy_imported": imported, "active_profile": active}

    def list_profiles(self, owner_user_id: str) -> list[dict]:
        owner = _owner_id(owner_user_id)
        with self._lock, self._connection() as conn, conn:
            self._ensure_state(conn, owner)
            rows = conn.execute(
                """SELECT * FROM format_profiles WHERE owner_user_id=?
                   ORDER BY updated_at DESC, name_key ASC""",
                (owner,),
            ).fetchall()
            return [self._metadata_from_row(row) for row in rows]

    def get(self, owner_user_id: str, profile_id: str) -> dict:
        owner = _owner_id(owner_user_id)
        with self._lock, self._connection() as conn:
            return self._profile_from_row(self._owned_row(conn, owner, profile_id))

    def create(self, owner_user_id: str, name_value: str, config: dict) -> dict:
        owner = _owner_id(owner_user_id)
        name, name_key = _profile_name(name_value)
        payload, schema_version = _profile_config(config)
        profile_id = f"fmt_{secrets.token_hex(8)}"
        now = self._now_int()
        with self._lock, self._connection() as conn, conn:
            self._ensure_state(conn, owner)
            try:
                conn.execute(
                    """INSERT INTO format_profiles
                       (profile_id, owner_user_id, name, name_key, config_json,
                        schema_version, revision, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        profile_id,
                        owner,
                        name,
                        name_key,
                        payload,
                        schema_version,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise FormatProfileError("WPS_FORMAT_PROFILE_NAME_CONFLICT") from exc
            conn.execute(
                """UPDATE format_profile_state SET active_profile_id=?, updated_at=?
                   WHERE owner_user_id=?""",
                (profile_id, now, owner),
            )
            return self._profile_from_row(self._owned_row(conn, owner, profile_id))

    def update(
        self, owner_user_id: str, profile_id: str, name_value: str, config: dict
    ) -> dict:
        owner = _owner_id(owner_user_id)
        name, name_key = _profile_name(name_value)
        payload, schema_version = _profile_config(config)
        now = self._now_int()
        with self._lock, self._connection() as conn, conn:
            row = self._owned_row(conn, owner, profile_id)
            try:
                conn.execute(
                    """UPDATE format_profiles SET
                       name=?, name_key=?, config_json=?, schema_version=?,
                       revision=?, updated_at=?
                       WHERE profile_id=? AND owner_user_id=?""",
                    (
                        name,
                        name_key,
                        payload,
                        schema_version,
                        int(row["revision"]) + 1,
                        now,
                        profile_id,
                        owner,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise FormatProfileError("WPS_FORMAT_PROFILE_NAME_CONFLICT") from exc
            self._ensure_state(conn, owner)
            conn.execute(
                """UPDATE format_profile_state SET active_profile_id=?, updated_at=?
                   WHERE owner_user_id=?""",
                (profile_id, now, owner),
            )
            return self._profile_from_row(self._owned_row(conn, owner, profile_id))

    def delete(self, owner_user_id: str, profile_id: str) -> dict:
        owner = _owner_id(owner_user_id)
        now = self._now_int()
        with self._lock, self._connection() as conn, conn:
            self._owned_row(conn, owner, profile_id)
            state = self._ensure_state(conn, owner)
            active_profile_id = str(state["active_profile_id"] or "")
            conn.execute(
                "DELETE FROM format_profiles WHERE profile_id=? AND owner_user_id=?",
                (profile_id, owner),
            )
            if active_profile_id == profile_id:
                active_profile_id = ""
                conn.execute(
                    """UPDATE format_profile_state
                       SET active_profile_id='', updated_at=? WHERE owner_user_id=?""",
                    (now, owner),
                )
            return {"deleted": True, "active_profile_id": active_profile_id}

    def select(self, owner_user_id: str, profile_id: str) -> dict | None:
        owner = _owner_id(owner_user_id)
        now = self._now_int()
        with self._lock, self._connection() as conn, conn:
            self._ensure_state(conn, owner)
            if profile_id:
                self._owned_row(conn, owner, profile_id)
            conn.execute(
                """UPDATE format_profile_state SET active_profile_id=?, updated_at=?
                   WHERE owner_user_id=?""",
                (profile_id, now, owner),
            )
            if not profile_id:
                return None
            return self._profile_from_row(self._owned_row(conn, owner, profile_id))

    def _active_profile_with_connection(
        self, conn: sqlite3.Connection, owner: str, state: sqlite3.Row
    ) -> dict | None:
        profile_id = str(state["active_profile_id"] or "")
        if not profile_id:
            return None
        return self._profile_from_row(self._owned_row(conn, owner, profile_id))

    def active_profile(self, owner_user_id: str) -> dict | None:
        owner = _owner_id(owner_user_id)
        with self._lock, self._connection() as conn, conn:
            state = self._ensure_state(conn, owner)
            return self._active_profile_with_connection(conn, owner, state)


__all__ = [
    "FormatProfileError",
    "FormatProfileStore",
    "format_profile_database_path",
]
