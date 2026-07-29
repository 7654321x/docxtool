"""Public, JSON-safe models returned by the recognition SDK.

The SDK deliberately returns paragraph anchors and structural decisions rather
than source text.  A host application such as a WPS add-in already owns the
open document and can use the anchors to apply formatting safely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class ReviewItem:
    """A non-sensitive recognition decision that should be surfaced for review."""

    block_index: int
    source_paragraph_index: Optional[int]
    final_type: str
    level: str
    confidence: float
    reasons: Tuple[str, ...]
    evidence: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_index": self.block_index,
            "source_paragraph_index": self.source_paragraph_index,
            "final_type": self.final_type,
            "level": self.level,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class RecognitionBlock:
    """One recognized document block with stable anchors for a host document."""

    block_index: int
    source_paragraph_index: Optional[int]
    kind: str
    type_id: str
    section: str
    text_sha256: str
    previous_text_sha256: str
    next_text_sha256: str
    format_role: str
    review_level: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_index": self.block_index,
            "source_paragraph_index": self.source_paragraph_index,
            "kind": self.kind,
            "type_id": self.type_id,
            "section": self.section,
            "text_sha256": self.text_sha256,
            "previous_text_sha256": self.previous_text_sha256,
            "next_text_sha256": self.next_text_sha256,
            "format_role": self.format_role,
            "review_level": self.review_level,
        }


@dataclass(frozen=True)
class RecognitionPlan:
    """Versioned, read-only recognition result for a DOCX snapshot."""

    schema_version: str
    engine_version: str
    source_sha256: str
    processing_mode: str
    recognition_mode: str
    document_mode: str
    document_mode_confidence: float
    blocks: Tuple[RecognitionBlock, ...]
    review_items: Tuple[ReviewItem, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "source_sha256": self.source_sha256,
            "processing_mode": self.processing_mode,
            "recognition_mode": self.recognition_mode,
            "document_mode": self.document_mode,
            "document_mode_confidence": self.document_mode_confidence,
            "blocks": [block.to_dict() for block in self.blocks],
            "review_items": [item.to_dict() for item in self.review_items],
        }
