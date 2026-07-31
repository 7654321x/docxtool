"""Public facade over the existing DOCX recognition pipeline."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from docxtool import __version__ as PACKAGE_VERSION
from docxtool.document.importer import DocxImporter, ParagraphData
from docxtool.document.recognition.version import (
    RECOGNITION_DIAGNOSTIC_SCHEMA_VERSION,
    RECOGNITION_ENGINE_VERSION,
)
from docxtool.document.style_config import load_rules_and_settings
from docxtool.document.source_tape import (
    HOST_TEXT_CONTRACT_VERSION,
    SOURCE_LOCATOR_VERSION,
    SourceTape,
    canonicalize_text,
    utf16_length,
)
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


def _source_locator(paragraph: ParagraphData) -> dict:
    """Return a verified v2 source locator without exposing text by default."""
    features = getattr(paragraph, "features", None)
    physical_index = _source_paragraph_index(paragraph)
    physical_text = str(getattr(features, "source_physical_text", "") or "")
    tape = SourceTape.from_text(physical_text)
    start = getattr(features, "source_start_utf16", None)
    end = getattr(features, "source_end_utf16", None)
    canonical_start = getattr(features, "source_canonical_start_utf16", None)
    canonical_end = getattr(features, "source_canonical_end_utf16", None)
    physical_length = utf16_length(physical_text)
    canonical_length = utf16_length(tape.canonical_text)
    valid_offsets = (
        physical_index is not None
        and isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start <= end <= physical_length
    )
    raw_fragment = ""
    canonical_fragment = ""
    evidence = list(getattr(features, "source_locator_evidence", ()) or ())
    warnings = list(getattr(features, "source_locator_warnings", ()) or ())
    status = str(getattr(features, "source_locator_status", "unresolved") or "unresolved")
    verified = False
    if valid_offsets:
        raw_fragment = tape.raw_slice_utf16(start, end) or ""
        canonical_fragment = canonicalize_text(raw_fragment)
        expected_raw = str(getattr(features, "source_fragment_text", "") or "")
        expected_canonical = str(getattr(features, "source_canonical_fragment_text", "") or "")
        canonical_valid = (
            isinstance(canonical_start, int)
            and isinstance(canonical_end, int)
            and 0 <= canonical_start <= canonical_end <= canonical_length
            and tape.raw_span_for_canonical_range(canonical_start, canonical_end) is not None
        )
        if raw_fragment == expected_raw and canonical_fragment == expected_canonical and canonical_valid:
            evidence.append("RAW_RANGE_READBACK_MATCH")
            verified = status == "confirmed"
        else:
            status = "unresolved"
            warnings.append("SOURCE_TEXT_HASH_MISMATCH")
    else:
        status = "unresolved"
        warnings.append("SOURCE_RANGE_UNRESOLVED")
    return {
        "physical_index": physical_index,
        "physical_hash": _sha256_text(physical_text) if physical_index is not None else "",
        "physical_canonical_hash": _sha256_text(tape.canonical_text) if physical_index is not None else "",
        "physical_length": physical_length,
        "physical_canonical_length": canonical_length,
        "raw_start": start if valid_offsets else None,
        "raw_end": end if valid_offsets else None,
        "canonical_start": canonical_start if valid_offsets else None,
        "canonical_end": canonical_end if valid_offsets else None,
        "raw_fragment": raw_fragment,
        "canonical_fragment": canonical_fragment,
        "status": status,
        "verified": verified,
        "evidence": tuple(dict.fromkeys(evidence)),
        "warnings": tuple(dict.fromkeys(warnings)),
    }


def _safe_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, (str, int, float)))


def _segment_format_features(paragraph: ParagraphData) -> dict:
    """Expose non-sensitive run-intersection features for one logical block."""
    features = getattr(paragraph, "features", None)
    if features is None:
        return {}
    return {
        "font_name": str(getattr(features, "segment_font_name", "") or ""),
        "dominant_font_name": str(getattr(features, "segment_dominant_font_name", "") or ""),
        "font_name_east_asia": str(getattr(features, "segment_font_name_east_asia", "") or ""),
        "font_name_ascii": str(getattr(features, "segment_font_name_ascii", "") or ""),
        "font_size_pt": getattr(features, "segment_font_size_pt", None),
        "weighted_font_size_pt": getattr(features, "segment_weighted_font_size_pt", None),
        "bold_char_ratio": float(getattr(features, "segment_bold_char_ratio", 0.0) or 0.0),
        "italic_char_ratio": float(getattr(features, "segment_italic_char_ratio", 0.0) or 0.0),
        "underline_char_ratio": float(getattr(features, "segment_underline_char_ratio", 0.0) or 0.0),
        "explicit_format_ratio": float(getattr(features, "segment_explicit_format_ratio", 0.0) or 0.0),
        "inherited_format_ratio": float(getattr(features, "segment_inherited_format_ratio", 0.0) or 0.0),
        "run_count": int(getattr(features, "segment_run_count", 0) or 0),
        "visible_char_count": int(getattr(features, "segment_visible_char_count", 0) or 0),
        "mapped_format_char_count": int(
            getattr(features, "segment_mapped_format_char_count", 0) or 0
        ),
        "format_coverage_ratio": float(
            getattr(features, "segment_format_coverage_ratio", 0.0) or 0.0
        ),
        "format_status": str(getattr(features, "segment_format_status", "unknown") or "unknown"),
        "format_warnings": list(getattr(features, "segment_format_warnings", ()) or ()),
        "format_sources": list(getattr(features, "segment_format_sources", ()) or ()),
        "style_name": str(getattr(features, "segment_style_name", "") or ""),
        "has_mixed_fonts": bool(getattr(features, "segment_has_mixed_fonts", False)),
        "has_mixed_sizes": bool(getattr(features, "segment_has_mixed_sizes", False)),
        "numbering_features": str(getattr(features, "segment_numbering_features", "") or ""),
        "alignment": str(getattr(features, "segment_alignment", "") or ""),
        "position_in_physical_paragraph": str(
            getattr(features, "segment_position_in_physical_paragraph", "whole") or "whole"
        ),
    }


def _request_features(
    processing_mode: str,
    recognition_mode: str,
    features: Optional[Mapping[str, Any]],
) -> dict:
    resolved = copy.deepcopy(dict(features or {}))
    processing = dict(resolved.get("processing") or {})
    processing["strategy"] = processing_mode
    # The SDK contract describes the same reliable heading/body boundary as
    # the renderer so a host can bind each logical range independently.
    processing["split_inline_heading_body"] = True
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


def _build_plan(
    data,
    source_sha256: str,
    include_text: bool = False,
    include_raw_text: bool = False,
) -> RecognitionPlan:
    paragraphs = list(getattr(data, "paragraphs", ()) or ())
    visible_hashes = [_sha256_text(_visible_text(item)) if _visible_text(item) else "" for item in paragraphs]
    report = getattr(data, "recognition_diagnostics", {}) or {}
    blocks = []
    review_items = []
    locators = [_source_locator(paragraph) for paragraph in paragraphs]
    physical_occurrences = {}
    occurrence_by_physical_index = {}
    segments_by_physical = {}
    for index, locator in enumerate(locators):
        physical_index = locator["physical_index"]
        physical_hash = locator["physical_hash"]
        if physical_index is None or not physical_hash or physical_index in occurrence_by_physical_index:
            continue
        occurrence_by_physical_index[physical_index] = physical_occurrences.get(physical_hash, 0)
        physical_occurrences[physical_hash] = occurrence_by_physical_index[physical_index] + 1
        segments_by_physical[physical_index] = []
    for index, locator in enumerate(locators):
        physical_index = locator["physical_index"]
        if physical_index is not None:
            segments_by_physical.setdefault(physical_index, []).append(index)
    segment_meta = {}
    for physical_index, indexes in segments_by_physical.items():
        # Importer preserves logical source order.  Keep that full order even
        # when one locator is unresolved, otherwise segment_count would lie.
        ordered = list(indexes)
        previous_end = -1
        for segment_index, index in enumerate(ordered):
            locator = locators[index]
            raw_start = locator["raw_start"]
            raw_end = locator["raw_end"]
            if raw_start is not None and raw_end is not None and raw_start < previous_end:
                locator["status"] = "unresolved"
                locator["verified"] = False
                locator["warnings"] = tuple(dict.fromkeys(locator["warnings"] + ("SOURCE_RANGE_OVERLAP",)))
            if raw_end is not None:
                previous_end = max(previous_end, raw_end)
            segment_meta[index] = (segment_index, len(ordered))
        located_count = sum(
            locators[index]["raw_start"] is not None and locators[index]["raw_end"] is not None
            for index in ordered
        )
        confirmed_count = sum(locators[index]["status"] == "confirmed" for index in ordered)
        for index in ordered:
            segment_index, total = segment_meta[index]
            segment_meta[index] = (segment_index, total, located_count, confirmed_count)
    for index, paragraph in enumerate(paragraphs):
        meta = dict(getattr(paragraph, "meta", {}) or {})
        type_id = str(getattr(paragraph, "type_id", "unknown") or "unknown")
        review_level = str(meta.get("review_level", "confirmed") or "confirmed")
        locator = locators[index]
        physical_index = locator["physical_index"]
        segment_index, segment_count, segment_located, segment_confirmed = segment_meta.get(index, (0, 0, 0, 0))
        prefix = ""
        suffix = ""
        if locator["raw_start"] is not None and locator["raw_end"] is not None:
            tape = SourceTape.from_text(str(getattr(getattr(paragraph, "features", None), "source_physical_text", "") or ""))
            prefix = tape.raw_slice_utf16(0, locator["raw_start"]) or ""
            suffix = tape.raw_slice_utf16(locator["raw_end"], locator["physical_length"]) or ""
        blocks.append(RecognitionBlock(
            block_index=index,
            source_paragraph_index=physical_index,
            physical_paragraph_index=physical_index,
            physical_occurrence_index=occurrence_by_physical_index.get(physical_index, 0),
            physical_text_sha256=locator["physical_hash"],
            physical_canonical_text_sha256=locator["physical_canonical_hash"],
            physical_text_length_utf16=locator["physical_length"],
            physical_canonical_text_length_utf16=locator["physical_canonical_length"],
            locator_version=SOURCE_LOCATOR_VERSION,
            segment_index=segment_index,
            segment_count=segment_count,
            segment_count_total=segment_count,
            segment_count_located=segment_located,
            segment_count_confirmed=segment_confirmed,
            raw_start_utf16=locator["raw_start"],
            raw_end_utf16=locator["raw_end"],
            canonical_start_utf16=locator["canonical_start"],
            canonical_end_utf16=locator["canonical_end"],
            range_start_utf16=locator["raw_start"],
            range_end_utf16=locator["raw_end"],
            locator_verified=locator["verified"],
            source_locator_status=locator["status"],
            source_locator_evidence=locator["evidence"],
            source_locator_warnings=locator["warnings"],
            kind=_SPECIAL_KIND_BY_TYPE.get(type_id, "paragraph"),
            type_id=type_id,
            section=str(meta.get("recognition_section", "body") or "body"),
            text_sha256=visible_hashes[index],
            text_length_utf16=utf16_length(_visible_text(paragraph)),
            previous_text_sha256=next((value for value in reversed(visible_hashes[:index]) if value), ""),
            next_text_sha256=next((value for value in visible_hashes[index + 1:] if value), ""),
            format_role=type_id,
            review_level=review_level,
            classification_confidence=float(meta.get("review_confidence", 0.0) or 0.0),
            classification_evidence=_safe_strings(meta.get("recognition_evidence")),
            review_reasons=_safe_strings(meta.get("review_reasons")),
            raw_fragment_sha256=_sha256_text(locator["raw_fragment"]) if locator["raw_fragment"] else "",
            canonical_fragment_sha256=_sha256_text(locator["canonical_fragment"]) if locator["canonical_fragment"] else "",
            prefix_context_sha256=_sha256_text(prefix) if prefix else "",
            suffix_context_sha256=_sha256_text(suffix) if suffix else "",
            segment_format=_segment_format_features(paragraph),
            recognized_text=_visible_text(paragraph) if include_text else None,
            raw_fragment_text=locator["raw_fragment"] if include_raw_text else None,
            canonical_fragment_text=locator["canonical_fragment"] if include_text else None,
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
        package_version=PACKAGE_VERSION,
        locator_version=SOURCE_LOCATOR_VERSION,
        host_text_contract_version=HOST_TEXT_CONTRACT_VERSION,
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
    include_raw_text: bool = False,
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
    if not isinstance(include_text, bool) or not isinstance(include_raw_text, bool):
        raise RecognitionInputError("include_text 和 include_raw_text 必须为布尔值")
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
    return _build_plan(
        data,
        _sha256_file(path),
        include_text=include_text,
        include_raw_text=include_raw_text,
    )
