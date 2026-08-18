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
from .document_mode import has_doc_type_keyword, has_title_keyword, legacy_heading_addressing_score
from .features import DocumentBlock, ParagraphFeatures, extract_blocks, extract_features
from .front_matter import (
    legacy_author_line_score,
    legacy_date_line_score,
    legacy_role_name_score,
    legacy_title_cont_score,
    legacy_title_score,
)
from .metadata import enrich_legacy_type_metadata
from .model import DocumentMode, DocumentModeDecision, ParagraphType, RecognitionSummary, SectionKind
from .numbering import (
    find_numbered_bold_pos,
    legacy_numbered_heading_score,
    looks_like_damaged_heading,
    match_numbering,
    match_style_or_level,
)
from .opening_speech import opening_speech_title_text, strip_inferred_speech_numbering
from .selection import build_legacy_scorer_registry, select_legacy_scored_type
from .signature import (
    blocks_independent_sign_date,
    has_signature_org_shape,
    is_body_tail_context,
    is_signature_org_candidate,
    starts_with_signature_negative,
)
from .state import (
    LEGACY_FLOW,
    legacy_flow_allows,
    legacy_record_structural,
    legacy_repair_heading2_continuation,
    legacy_repair_heading4_colon,
    legacy_repair_heading_level,
    legacy_repair_ocr_heading,
    legacy_update_context_after_type,
)
from .tail_structure import detect_legacy_tail_structural_type
from .validators import validate_diagnostics, validate_sequence

__all__ = ["DEFAULT_CONFIG", "DocumentBlock", "DocumentMode", "DocumentModeDecision", "LEGACY_FLOW", "ParagraphFeatures", "ParagraphType", "RecognitionConfig", "RecognitionSummary", "SectionKind", "apply_recognition", "blocks_independent_sign_date", "build_legacy_scorer_registry", "can_start_attachment_note", "detect_legacy_tail_structural_type", "diagnostics_to_json", "enrich_legacy_type_metadata", "extract_blocks", "extract_features", "find_numbered_bold_pos", "has_doc_type_keyword", "has_signature_org_shape", "has_title_keyword", "is_attachment_boundary_text", "is_attachment_item_text", "is_attachment_note_text", "is_body_tail_context", "is_signature_org_candidate", "legacy_author_line_score", "legacy_date_line_score", "legacy_flow_allows", "legacy_heading_addressing_score", "legacy_numbered_heading_score", "legacy_record_structural", "legacy_repair_heading2_continuation", "legacy_repair_heading4_colon", "legacy_repair_heading_level", "legacy_repair_ocr_heading", "legacy_role_name_score", "legacy_title_cont_score", "legacy_title_score", "legacy_update_context_after_type", "looks_like_damaged_heading", "match_attachment_item", "match_attachment_note", "match_numbering", "match_style_or_level", "opening_speech_title_text", "resolve_render_mapping", "select_legacy_scored_type", "starts_with_signature_negative", "strip_inferred_speech_numbering", "validate_diagnostics", "validate_sequence"]
