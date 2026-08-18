"""Compatibility facade for neutral punctuation text helpers."""

from docxtool.document.text.punctuation import (
    PUNCTUATION_MODES,
    ProtectedSpan,
    PunctuationReplacement,
    PunctuationResult,
    apply_punctuation_replacements,
    find_protected_spans,
    normalize_punctuation,
    normalize_punctuation_text,
    plan_punctuation_replacements,
)

__all__ = [
    "PUNCTUATION_MODES",
    "ProtectedSpan",
    "PunctuationReplacement",
    "PunctuationResult",
    "apply_punctuation_replacements",
    "find_protected_spans",
    "normalize_punctuation",
    "normalize_punctuation_text",
    "plan_punctuation_replacements",
]
