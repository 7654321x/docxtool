"""Structured recognition layer for imported document paragraphs."""

from .decoder import apply_recognition
from .diagnostics import diagnostics_to_json
from .compatibility import resolve_render_mapping
from .config import DEFAULT_CONFIG, RecognitionConfig
from .features import DocumentBlock, ParagraphFeatures, extract_blocks, extract_features
from .model import DocumentMode, DocumentModeDecision, ParagraphType, RecognitionSummary, SectionKind
from .opening_speech import opening_speech_title_text, strip_inferred_speech_numbering
from .validators import validate_diagnostics, validate_sequence

__all__ = ["DEFAULT_CONFIG", "DocumentBlock", "DocumentMode", "DocumentModeDecision", "ParagraphFeatures", "ParagraphType", "RecognitionConfig", "RecognitionSummary", "SectionKind", "apply_recognition", "diagnostics_to_json", "extract_blocks", "extract_features", "opening_speech_title_text", "resolve_render_mapping", "strip_inferred_speech_numbering", "validate_diagnostics", "validate_sequence"]
