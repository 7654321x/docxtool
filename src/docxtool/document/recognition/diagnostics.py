"""Safe serialization of recognition diagnostics."""

from __future__ import annotations

import json
from typing import Any


def diagnostics_to_json(value: dict[str, Any], *, indent: int | None = 2) -> str:
    """Serialize diagnostics without source paragraph text or OOXML objects."""
    allowed = {"engine_version", "schema_version", "config", "mode", "mode_confidence", "mode_evidence", "beam_width", "blocks", "candidate_trace", "paragraphs", "validation", "structure_tree", "structure_error"}
    safe = {key: item for key, item in value.items() if key in allowed}
    return json.dumps(safe, ensure_ascii=False, indent=indent, sort_keys=True, default=str)
