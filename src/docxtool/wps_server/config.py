"""Fixed first-phase WPS service configuration."""

from __future__ import annotations

import os
from pathlib import Path

from docxtool.paths import project_path, var_path

WPS_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
WPS_HEARTBEAT_INTERVAL_SECONDS = 10 * 60
WPS_OFFLINE_AFTER_SECONDS = 30 * 60
WPS_JSON_MAX_BYTES = 32 * 1024
WPS_CONTROLLED_COMMANDS = frozenset({"apply"})


def _parse_server_bool(name: str, value: str | None, *, default: bool) -> bool:
    """Parse a server-only boolean setting and fail closed on malformed values."""
    if value is None or not str(value).strip():
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name}_INVALID")


def resolve_wps_admin_mutations_enabled(value: str | None = None) -> bool:
    """Return the process-startup WPS admin-mutation gate, disabled by default."""
    configured = os.environ.get("WPS_ADMIN_MUTATIONS_ENABLED") if value is None else value
    return _parse_server_bool(
        "WPS_ADMIN_MUTATIONS_ENABLED", configured, default=False
    )


WPS_ADMIN_MUTATIONS_ENABLED = resolve_wps_admin_mutations_enabled()


def resolve_wps_database_path(value=None) -> Path:
    """Return the configured WPS database path without creating it."""
    configured = value if value is not None else os.environ.get("WPS_DATABASE_PATH")
    if not configured:
        return var_path("data", "wps_plugin.db")
    path = Path(configured)
    return path if path.is_absolute() else project_path(str(path))


def require_separate_database_paths(web_database_path, wps_database_path) -> None:
    """Fail before initialization when Web and WPS resolve to the same file."""
    web_path = os.path.normcase(str(Path(web_database_path).resolve()))
    wps_path = os.path.normcase(str(Path(wps_database_path).resolve()))
    if web_path == wps_path:
        raise RuntimeError("WPS_DATABASE_PATH_CONFLICT")


def public_feature_manifest() -> dict:
    """Return the fixed first-phase local and controlled feature list."""
    return {
        "local": [
            "panel",
            "health",
            "settings",
            "preview",
            "reader",
            "clear_preview",
        ],
        "controlled": [
            {
                "command": "apply",
                "name": "一键排版",
                "enabled": True,
                "authorization_required": True,
            }
        ],
    }
