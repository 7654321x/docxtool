"""Logical segmentation helpers.

This package owns source-coordinate conservation and physical-to-logical
paragraph boundary helpers.  Importer keeps compatibility aliases while the
implementation moves here step by step.
"""

from docxtool.document.segmentation.source_locator import (
    apply_segment_format_features,
    inherit_source_locator,
    set_source_locator,
    source_line_spans,
    trim_source_span,
    utf16_length_of,
    visible_character_count,
)
from docxtool.document.segmentation.boundaries import (
    has_format_transition,
    has_inline_lead_bold_transition,
    is_strong_soft_line_structure,
    segment_boundary_candidates,
    source_starts_body_region,
    split_inline_heading_body_spans,
    split_structural_tail_after_numbered_heading,
    validate_numbered_heading_body_split,
    validate_source_span_partition,
)

__all__ = [
    "apply_segment_format_features",
    "has_format_transition",
    "has_inline_lead_bold_transition",
    "inherit_source_locator",
    "is_strong_soft_line_structure",
    "segment_boundary_candidates",
    "set_source_locator",
    "source_line_spans",
    "source_starts_body_region",
    "split_inline_heading_body_spans",
    "split_structural_tail_after_numbered_heading",
    "trim_source_span",
    "utf16_length_of",
    "validate_numbered_heading_body_split",
    "validate_source_span_partition",
    "visible_character_count",
]
