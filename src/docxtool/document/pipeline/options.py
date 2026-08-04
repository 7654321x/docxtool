"""Import processing-mode and text/token strategy construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List

from docxtool.document.models import InlineToken


@dataclass(frozen=True)
class ImportProcessingOptions:
    """Resolved importer switches and their existing normalization callbacks."""

    strict_preservation: bool
    structural_preservation: bool
    processing_strategy: str
    split_inline_heading_body: bool
    recognition_mode: str
    numbering_enabled: bool
    normalize_text: Callable[[str], str]
    normalize_tokens: Callable[[List[InlineToken]], List[InlineToken]]


def resolve_import_processing_options(
    features: dict,
    *,
    strict_preservation: bool,
    recognition_mode: str,
    feature_bool_func: Callable[[Any, bool], bool],
    normalize_basic_text_func: Callable[[str], str],
    normalize_quotes_func: Callable[[str], str],
    to_chinese_punctuation_func: Callable[[str], str],
    normalize_inline_tokens_func: Callable[[List[InlineToken], bool], List[InlineToken]],
    inline_token_type: type,
    import_error_type: type[Exception],
) -> ImportProcessingOptions:
    """Resolve the legacy importer options without changing their precedence."""

    processing_options = (
        features.get("processing", {})
        if isinstance(features.get("processing", {}), dict)
        else {}
    )
    requested_strategy = str(
        processing_options.get("strategy") or processing_options.get("mode") or ""
    ).strip().lower()
    requested_strategy = {"smart": "structural"}.get(requested_strategy, requested_strategy)
    if requested_strategy:
        if requested_strategy not in {"strict", "structural", "normalize"}:
            raise import_error_type("处理模式必须为 strict、smart、structural 或 normalize")
        processing_strategy = requested_strategy
    elif "strict_preservation" in processing_options:
        processing_strategy = "strict" if feature_bool_func(
            processing_options.get("strict_preservation"), strict_preservation
        ) else "normalize"
    else:
        processing_strategy = "strict" if strict_preservation else "normalize"

    strict_preservation = processing_strategy == "strict"
    structural_preservation = processing_strategy == "structural"
    split_inline_heading_body = structural_preservation and feature_bool_func(
        processing_options.get("split_inline_heading_body", True), True
    )

    recognition_options = (
        features.get("recognition", {})
        if isinstance(features.get("recognition", {}), dict)
        else {}
    )
    recognition_mode = str(
        recognition_options.get("mode", recognition_mode) or recognition_mode
    ).lower()
    if recognition_mode not in {"legacy", "shadow", "authoritative"}:
        raise import_error_type("识别模式必须为 legacy、shadow 或 authoritative")

    punctuation_options = (
        features.get("punctuation", {})
        if isinstance(features.get("punctuation", {}), dict)
        else {}
    )
    numbering_options = (
        features.get("numbering", {})
        if isinstance(features.get("numbering", {}), dict)
        else {}
    )
    numbering_enabled = feature_bool_func(numbering_options.get("enabled", False), False)
    new_punctuation_enabled = feature_bool_func(
        punctuation_options.get("enabled", False), False
    )
    punctuation_mode = str(punctuation_options.get("mode", "safe") or "safe")
    punctuation_enabled = feature_bool_func(features.get("punctuation_enabled", True), True)
    punctuation_requested = new_punctuation_enabled or punctuation_enabled

    def normalize_text(text: str) -> str:
        if not text:
            return text
        if strict_preservation:
            return text
        if structural_preservation and not punctuation_requested:
            return text
        if new_punctuation_enabled:
            from docxtool.document.text.punctuation import normalize_punctuation_text

            return normalize_punctuation_text(
                normalize_basic_text_func(text), mode=punctuation_mode
            )
        if punctuation_enabled:
            return to_chinese_punctuation_func(
                normalize_quotes_func(normalize_basic_text_func(text))
            )
        return text

    def normalize_tokens(tokens: List[InlineToken]) -> List[InlineToken]:
        if strict_preservation:
            return list(tokens or [])
        if structural_preservation and not punctuation_requested:
            return list(tokens or [])
        normalized = normalize_inline_tokens_func(
            tokens, punctuation_enabled and not new_punctuation_enabled
        )
        if not new_punctuation_enabled:
            if not punctuation_enabled:
                return normalized
            return [
                inline_token_type(token.kind, normalize_basic_text_func(token.text))
                if token.kind == "text"
                else token
                for token in normalized
            ]
        return [
            inline_token_type(token.kind, normalize_text(token.text))
            if token.kind == "text"
            else token
            for token in normalized
        ]

    return ImportProcessingOptions(
        strict_preservation=strict_preservation,
        structural_preservation=structural_preservation,
        processing_strategy=processing_strategy,
        split_inline_heading_body=split_inline_heading_body,
        recognition_mode=recognition_mode,
        numbering_enabled=numbering_enabled,
        normalize_text=normalize_text,
        normalize_tokens=normalize_tokens,
    )
