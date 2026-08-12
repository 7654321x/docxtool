"""Stable document data models.

These models form the compatibility contract between importer, segmentation,
recognition, normalization, renderer, and SDK code.
"""

from docxtool.document.models.document import (
    BodyBlock,
    DocumentData,
    NormalizationChange,
)
from docxtool.document.models.paragraph import (
    InlineToken,
    NativeNumbering,
    ParagraphData,
    ParagraphFeatures,
)
from docxtool.document.models.source import (
    SegmentBoundaryCandidate,
    SourceRun,
)

__all__ = [
    "BodyBlock",
    "DocumentData",
    "InlineToken",
    "NativeNumbering",
    "NormalizationChange",
    "ParagraphData",
    "ParagraphFeatures",
    "SegmentBoundaryCandidate",
    "SourceRun",
]
