"""Recognition-post normalization helpers.

This package contains steps that consume final recognition results and prepare
the document model for rendering without owning classification decisions.
"""

from docxtool.document.normalization.tail import (
    normalize_tail_structures,
    sync_recognition_consistency,
)

__all__ = [
    "normalize_tail_structures",
    "sync_recognition_consistency",
]
