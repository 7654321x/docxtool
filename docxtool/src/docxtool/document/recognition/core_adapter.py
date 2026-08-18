"""Adapter from imported paragraph models to the Core classifier facts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable


def apply_core_classification(
    data: Any,
    features: dict,
    *,
    feature_bool_func: Callable[[Any, bool], bool],
    classify_paragraphs_func: Callable[..., list],
    classification_options_type: type,
    paragraph_features_type: type,
) -> None:
    """Run the existing Core adapter and write its diagnostic metadata."""

    raw_options = features.get("classification", {})
    classification_options = raw_options if isinstance(raw_options, dict) else {}
    if not feature_bool_func(classification_options.get("enabled", True), True):
        return
    threshold = classification_options.get("minimum_auto_format_confidence", 0.85)
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        threshold = 0.85

    candidates = []
    indexes = []
    for index, paragraph in enumerate(data.paragraphs):
        if paragraph.type_id.startswith("__"):
            continue
        paragraph_features = paragraph.features or paragraph_features_type()
        candidates.append(
            SimpleNamespace(
                text=paragraph.original_text or paragraph.text,
                style_name=paragraph_features.style_name,
                alignment=paragraph_features.alignment,
                first_line_indent=paragraph_features.first_line_indent,
                font_size_pt=paragraph_features.font_size_pt,
                bold=paragraph_features.bold,
                native_numbering=bool(paragraph_features.numbering_prefix),
            )
        )
        indexes.append(index)
    if not candidates:
        return

    results = classify_paragraphs_func(
        candidates,
        classification_options_type(auto_format_threshold=threshold),
    )
    for paragraph_index, result in zip(indexes, results):
        meta = dict(data.paragraphs[paragraph_index].meta or {})
        meta["classification_kind"] = result.kind.value
        meta["classification_confidence"] = round(result.confidence, 3)
        meta["classification_auto_format"] = bool(result.auto_format)
        data.paragraphs[paragraph_index].meta = meta
