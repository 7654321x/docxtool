"""Structured recognition layer for imported document paragraphs."""

from .decoder import apply_recognition
from .diagnostics import diagnostics_to_json
from .attachment import (
    can_start_attachment_note,
    is_attachment_boundary_text,
    is_attachment_item_text,
    is_attachment_note_text,
    match_attachment_item,
    match_attachment_note,
)
from .compatibility import resolve_render_mapping
from .config import DEFAULT_CONFIG, RecognitionConfig
from .features import DocumentBlock, ParagraphFeatures, extract_blocks, extract_features
from .model import DocumentMode, DocumentModeDecision, ParagraphType, RecognitionSummary, SectionKind
from .numbering import (
    find_numbered_bold_pos,
    looks_like_damaged_heading,
    match_numbering,
    match_style_or_level,
)
from .opening_speech import opening_speech_title_text, strip_inferred_speech_numbering
from .signature import has_signature_org_shape, starts_with_signature_negative
from .validators import validate_diagnostics, validate_sequence

__all__ = ["DEFAULT_CONFIG", "DocumentBlock", "DocumentMode", "DocumentModeDecision", "ParagraphFeatures", "ParagraphType", "RecognitionConfig", "RecognitionSummary", "SectionKind", "apply_recognition", "can_start_attachment_note", "diagnostics_to_json", "extract_blocks", "extract_features", "find_numbered_bold_pos", "has_signature_org_shape", "is_attachment_boundary_text", "is_attachment_item_text", "is_attachment_note_text", "looks_like_damaged_heading", "match_attachment_item", "match_attachment_note", "match_numbering", "match_style_or_level", "opening_speech_title_text", "resolve_render_mapping", "starts_with_signature_negative", "strip_inferred_speech_numbering", "validate_diagnostics", "validate_sequence"]
