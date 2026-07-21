"""Finite, side-effect-free structural validators."""

from __future__ import annotations

from collections.abc import Sequence

from .model import ParagraphType


def validate_sequence(types: Sequence[str]) -> tuple[dict, ...]:
    issues: list[dict] = []
    normalized = [str(item) for item in types]
    for index, value in enumerate(normalized):
        if value in {ParagraphType.DISPATCH_NUMBER.value, ParagraphType.TITLE_CONTINUATION.value} and index > 0 and normalized[index - 1] == ParagraphType.BODY.value:
            issues.append({"code": "HEAD_AFTER_BODY", "index": index, "type": value})
        if value == ParagraphType.MEETING_META.value and index == 0:
            issues.append({"code": "MEETING_META_AT_DOCUMENT_START", "index": index})
    return tuple(issues)


def validate_diagnostics(diagnostics: dict) -> dict:
    paragraphs = diagnostics.get("paragraphs", ()) if isinstance(diagnostics, dict) else ()
    types = [item.get("final_type", item.get("type", "")) for item in paragraphs if isinstance(item, dict)]
    issues = validate_sequence(types)
    return {"ok": not issues, "issues": list(issues)}
