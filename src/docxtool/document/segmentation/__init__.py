"""Logical segmentation helpers.

This package owns source-coordinate conservation and physical-to-logical
paragraph boundary helpers.  Importer keeps compatibility aliases while the
implementation moves here step by step.
"""

from docxtool.document.segmentation.source_locator import (
    apply_segment_format_features,
    assign_segment_ordinals,
    build_segment_features,
    build_unresolved_empty_segment_features,
    inherit_source_locator,
    set_source_locator,
    source_line_spans,
    trim_source_span,
    utf16_length_of,
    visible_character_count,
)
from docxtool.document.segmentation.boundaries import (
    heading_has_inline_body,
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
from docxtool.document.segmentation.pipeline import (
    LogicalSpanPlan,
    build_logical_span_plan,
)
from docxtool.document.segmentation.soft_breaks import should_split_structural_line_breaks
from docxtool.document.segmentation.soft_breaks import (
    is_header_role_date_pair,
    is_dispatch_number_line,
    is_role_name_line,
)
from docxtool.document.segmentation.body_tail import find_last_body_candidate_index

__all__ = [
    "apply_segment_format_features",
    "assign_segment_ordinals",
    "build_segment_features",
    "build_logical_span_plan",
    "build_unresolved_empty_segment_features",
    "find_last_body_candidate_index",
    "heading_has_inline_body",
    "has_format_transition",
    "has_inline_lead_bold_transition",
    "inherit_source_locator",
    "is_header_role_date_pair",
    "is_dispatch_number_line",
    "is_role_name_line",
    "is_strong_soft_line_structure",
    "LogicalSpanPlan",
    "segment_boundary_candidates",
    "set_source_locator",
    "should_split_structural_line_breaks",
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
