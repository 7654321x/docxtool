"""Compatibility facade for the neutral read-only document structure model."""

from docxtool.document.analysis.document_structure import (
    BOUNDARY_RULES,
    AttachmentBlock,
    BlockKind,
    BlockSpan,
    BodyBlock,
    BoundaryRule,
    CONFIRMED_CONFIDENCE,
    DocumentStructure,
    ElementKind,
    ElementRef,
    TitleBlock,
    analyze_document_structure,
    validate_document_structure,
)

__all__ = [
    "BOUNDARY_RULES",
    "AttachmentBlock",
    "BlockKind",
    "BlockSpan",
    "BodyBlock",
    "BoundaryRule",
    "CONFIRMED_CONFIDENCE",
    "DocumentStructure",
    "ElementKind",
    "ElementRef",
    "TitleBlock",
    "AttachmentBlock",
    "analyze_document_structure",
    "validate_document_structure",
]
