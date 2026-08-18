"""Load the authoritative data-only format profile returned to WPS clients."""

from __future__ import annotations

import json

from docxtool.document.configuration.validation import validate_format_config
from docxtool.paths import default_format_config_path
from docxtool.version import package_version


def load_active_format_profile() -> dict:
    raw = json.loads(default_format_config_path().read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("FORMAT_CONFIG_INVALID")
    config = validate_format_config(raw)
    return {
        "config_version": f"docxtool-{package_version()}",
        "format_config": config,
    }
