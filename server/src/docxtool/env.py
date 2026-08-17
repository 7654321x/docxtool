"""Small .env loader for local server startup."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_file(path: str | Path) -> set[str]:
    """Load KEY=VALUE pairs from a .env file without overriding existing env vars."""

    env_path = Path(path)
    if not env_path.is_file():
        return set()

    loaded: set[str] = set()
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _clean_env_value(value)
        loaded.add(key)
    return loaded


def _clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
