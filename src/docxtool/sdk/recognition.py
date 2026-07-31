"""Public facade over the existing DOCX recognition pipeline."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from docxtool.document.importer import DocxImporter, ParagraphData
from docxtool.document.recognition.version import (
    RECOGNITION_DIAGNOSTIC_SCHEMA_VERSION,
    RECOGNITION_ENGINE_VERSION,
)
from docxtool.document.style_config import load_rules_and_settings
from docxtool.paths import default_format_config_path

from .models import RecognitionBlock, RecognitionPlan, ReviewItem


class RecognitionSdkError(RuntimeError):
    """Base error for the stable SDK boundary."""

    code = "RECOGNITION_FAILED"


class RecognitionInputError(RecognitionSdkError):
    """Raised when a caller does not provide a readable DOCX snapshot."""

    code = "INVALID_DOCX_INPUT"


_PROCESSING_MODES = frozenset({"strict", "structural", "normalize"})
_RECOGNITION_MODES = frozenset({"legacy", "shadow", "authoritative"})
_SPECIAL_KIND_BY_TYPE = {
    "__table__": "table",
    "__image__": "image",
    "__object_caption__": "caption",
    "__letterhead__": "letterhead",
}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _visible_text(paragraph: ParagraphData) -> str:
    return str(paragraph.original_text or paragraph.text or "")


def _source_paragraph_index(paragraph: ParagraphData) -> Optional[int]:
    features = getattr(paragraph, "features", None)
    value = getattr(features, "source_physical_paragraph_index", None)
    return value if isinstance(value, int) and value >= 0 else None


def _source_locator(paragraph: ParagraphData) -> tuple[Optional[int], str, int, Optional[int], Optional[int], bool]:
    features = getattr(paragraph, "features", None)
    physical_index = _source_paragraph_index(paragraph)
    physical_text = str(getattr(features, "source_physical_text", "") or "")
    start = getattr(features, "source_start_utf16", None)
    end = getattr(features, "source_end_utf16", None)
    physical_length = len(physical_text.encode("utf-16-le")) // 2
    valid_offsets = (
        physical_index is not None
        and isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start <= end <= physical_length
    )
    verified = False
    if valid_offsets:
        try:
            encoded = physical_text.encode("utf-16-le")
            selected = encoded[start * 2:end * 2].decode("utf-16-le")
            verified = selected == _visible_text(paragraph)
        except UnicodeError:
            verified = False
    return (
        physical_index,
        _sha256_text(physical_text) if physical_index is not None else "",
        physical_length,
        start if valid_offsets else None,
        end if valid_offsets else None,
        verified,
    )


def _safe_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, (str, int, float)))


def _request_features(
    processing_mode: str,
    recognition_mode: str,
    features: Optional[Mapping[str, Any]],
) -> dict:
    resolved = copy.deepcopy(dict(features or {}))
    processing = dict(resolved.get("processing") or {})
    processing["strategy"] = processing_mode
    resolved["processing"] = processing
    recognition = dict(resolved.get("recognition") or {})
    recognition["mode"] = recognition_mode
    resolved["recognition"] = recognition
    return resolved


def _load_rules_and_features(
    format_config: Optional[Mapping[str, Any]],
    feature_overrides: Optional[Mapping[str, Any]],
) -> tuple[list, dict]:
    if format_config is None:
        config = json.loads(default_format_config_path().read_text(encoding="utf-8"))
    elif isinstance(format_config, Mapping):
        config = copy.deepcopy(dict(format_config))
    else:
        raise RecognitionInputError("format_config 必须是格式配置对象")
    rules, _settings, configured_features = load_rules_and_settings(config)
    resolved_features = copy.deepcopy(configured_features)
    resolved_features.update(copy.deepcopy(dict(feature_overrides or {})))
    return rules, resolved_features


def _build_plan(data, source_sha256: str, include_text: bool = False) -> RecognitionPlan:
    paragraphs = list(getattr(data, "paragraphs", ()) or ())
    visible_hashes = [_sha256_text(_visible_text(item)) if _visible_text(item) else "" for item in paragraphs]
    report = getattr(data, "recognition_diagnostics", {}) or {}
    blocks = []
    review_items = []
    physical_occurrences = {}
    occurrence_by_physical_index = {}
    for paragraph in paragraphs:
        physical_index, physical_hash, _length, _start, _end, _verified = _source_locator(paragraph)
        if physical_index is None or not physical_hash or physical_index in occurrence_by_physical_index:
            continue
        occurrence_by_physical_index[physical_index] = physical_occurrences.get(physical_hash, 0)
        physical_occurrences[physical_hash] = occurrence_by_physical_index[physical_index] + 1
    for index, paragraph in enumerate(paragraphs):
        meta = dict(getattr(paragraph, "meta", {}) or {})
        type_id = str(getattr(paragraph, "type_id", "unknown") or "unknown")
        review_level = str(meta.get("review_level", "confirmed") or "confirmed")
        physical_index, physical_hash, physical_length, range_start, range_end, locator_verified = _source_locator(paragraph)
        blocks.append(RecognitionBlock(
            block_index=index,
            source_paragraph_index=physical_index,
            physical_paragraph_index=physical_index,
            physical_occurrence_index=occurrence_by_physical_index.get(physical_index, 0),
            physical_text_sha256=physical_hash,
            physical_text_length_utf16=physical_length,
            range_start_utf16=range_start,
            range_end_utf16=range_end,
            locator_verified=locator_verified,
            kind=_SPECIAL_KIND_BY_TYPE.get(type_id, "paragraph"),
            type_id=type_id,
            section=str(meta.get("recognition_section", "body") or "body"),
            text_sha256=visible_hashes[index],
            previous_text_sha256=next((value for value in reversed(visible_hashes[:index]) if value), ""),
            next_text_sha256=next((value for value in visible_hashes[index + 1:] if value), ""),
            format_role=type_id,
            review_level=review_level,
            recognized_text=_visible_text(paragraph) if include_text else None,
        ))
        if review_level in {"review", "critical_review"}:
            review_items.append(ReviewItem(
                block_index=index,
                source_paragraph_index=_source_paragraph_index(paragraph),
                final_type=type_id,
                level=review_level,
                confidence=float(meta.get("review_confidence", 0.0) or 0.0),
                reasons=_safe_strings(meta.get("review_reasons")),
                evidence=_safe_strings(meta.get("recognition_evidence")),
            ))
    return RecognitionPlan(
        schema_version=str(report.get("schema_version", RECOGNITION_DIAGNOSTIC_SCHEMA_VERSION)),
        engine_version=str(report.get("engine_version", RECOGNITION_ENGINE_VERSION)),
        source_sha256=source_sha256,
        processing_mode=str(getattr(data, "processing_strategy", "")),
        recognition_mode=str(getattr(data, "recognition_mode", "")),
        document_mode=str(report.get("mode", getattr(data, "doc_mode", "unknown"))),
        document_mode_confidence=float(report.get("mode_confidence", 0.0) or 0.0),
        blocks=tuple(blocks),
        review_items=tuple(review_items),
    )


def recognize_docx(
    source: str | Path,
    *,
    processing_mode: str = "structural",
    recognition_mode: str = "authoritative",
    format_config: Optional[Mapping[str, Any]] = None,
    features: Optional[Mapping[str, Any]] = None,
    include_text: bool = False,
) -> RecognitionPlan:
    """Recognize a local DOCX snapshot without starting the web service.

    The public result is intentionally text-free.  Host applications should
    keep the source document locally and use the returned anchors to look up
    the corresponding paragraphs before applying their own editor APIs.
    """
    path = Path(source).expanduser()
    if processing_mode not in _PROCESSING_MODES:
        raise RecognitionInputError("processing_mode 必须为 strict、structural 或 normalize")
    if recognition_mode not in _RECOGNITION_MODES:
        raise RecognitionInputError("recognition_mode 必须为 legacy、shadow 或 authoritative")
    if not isinstance(include_text, bool):
        raise RecognitionInputError("include_text 必须为布尔值")
    if path.suffix.lower() != ".docx" or not path.is_file():
        raise RecognitionInputError("source 必须是可读取的 .docx 文件")

    try:
        rules, configured_features = _load_rules_and_features(format_config, features)
        data = DocxImporter().load(
            str(path),
            rules,
            features=_request_features(processing_mode, recognition_mode, configured_features),
            recognition_mode=recognition_mode,
        )
    except RecognitionInputError:
        raise
    except Exception as exc:
        raise RecognitionSdkError(f"无法识别 DOCX：{type(exc).__name__}") from exc
    return _build_plan(data, _sha256_file(path), include_text=include_text)
