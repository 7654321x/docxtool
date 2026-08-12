"""Shared mutable state prepared once for a document export."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RenderContext:
    doc: Any
    section_relationship_parts: dict
    removed_external_relationships: list[dict]
    relationship_part_copier: Any
    referenced_style_copier: Any
    native_numbering_copier: Any
    section_part_copier: Any
    stats: dict
    page_rule: Any
    prev_was_title: bool
    prev_type_id: str
    body_flow_started: bool
    line_twips: int
    numbering_enabled: bool
    numbering_mode: str
    strict_preservation: bool
    normalization_processing: bool
    render_items: list
    paragraph_i: int
    deferred_body_log: list
    inline_heading_body_pairs: list
    section_paragraphs: list
    protected_paragraph_elements: set
    native_numbering_elements: set
    letterhead_detection: Any
    letterhead_enabled: bool
    preserve_input_letterhead: bool


def prepare_render_context(
    doc_data,
    rules,
    settings,
    output_path: str,
    numbering_options,
    letterhead_options,
    *,
    compatibility_module,
) -> RenderContext:
    doc = compatibility_module.Document()
    compatibility_module.ensure_document_styles(doc, rules, settings)
    section_relationship_parts = getattr(doc_data, "section_relationship_parts", {}) or {}
    removed_external_relationships: list[dict] = []
    relationship_part_copier = compatibility_module._SectionRelationshipCopier(
        doc.part.package,
        removed_external_relationships,
    )
    referenced_style_copier = compatibility_module._ReferencedStyleCopier(doc.styles.element)
    native_numbering_copier = compatibility_module._NativeNumberingCopier(
        doc.part.numbering_part.element
    )
    section_part_copier = relationship_part_copier if section_relationship_parts else None
    stats = {
        "total": len(doc_data.paragraphs),
        "heading1": 0, "heading1_report": 0, "heading2": 0, "heading3": 0, "heading4": 0,
        "body": 0, "fallback_count": 0, "style_fallback_count": 0, "numpr_removed": 0,
        "output_path": output_path,
        "removed_external_relationships": removed_external_relationships,
        "inline_heading_body_verified": 0,
        "native_numbering_preserved": 0,
    }
    page_rule = (
        rules[8]
        if len(rules) > 8
        else compatibility_module.StyleRule.default_for_row(8)
    )
    line_twips = compatibility_module._line_spacing_twips(settings)
    numbering_enabled = compatibility_module._feature_enabled(numbering_options, False)
    numbering_mode = str(
        compatibility_module._feature_options(numbering_options).get("mode", "safe")
        or "safe"
    ).lower()
    strict_preservation = bool(getattr(doc_data, "strict_preservation", False))
    normalization_processing = getattr(doc_data, "processing_strategy", "") == "normalize"
    render_items = (
        list(doc_data.paragraphs)
        if strict_preservation
        else compatibility_module._normalize_signature_attachment_order(doc_data.paragraphs)
    )
    if not strict_preservation:
        compatibility_module._validate_signature_attachment_order(render_items)
    letterhead_detection = (
        getattr(doc_data, "letterhead_detection", None)
        or compatibility_module.LetterheadDetection()
    )
    letterhead_enabled = compatibility_module._feature_enabled(letterhead_options, False)
    return RenderContext(
        doc=doc,
        section_relationship_parts=section_relationship_parts,
        removed_external_relationships=removed_external_relationships,
        relationship_part_copier=relationship_part_copier,
        referenced_style_copier=referenced_style_copier,
        native_numbering_copier=native_numbering_copier,
        section_part_copier=section_part_copier,
        stats=stats,
        page_rule=page_rule,
        prev_was_title=False,
        prev_type_id="",
        body_flow_started=False,
        line_twips=line_twips,
        numbering_enabled=numbering_enabled,
        numbering_mode=numbering_mode,
        strict_preservation=strict_preservation,
        normalization_processing=normalization_processing,
        render_items=render_items,
        paragraph_i=0,
        deferred_body_log=[],
        inline_heading_body_pairs=[],
        section_paragraphs=[],
        protected_paragraph_elements=set(),
        native_numbering_elements=set(),
        letterhead_detection=letterhead_detection,
        letterhead_enabled=letterhead_enabled,
        preserve_input_letterhead=not letterhead_enabled,
    )
