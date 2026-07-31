"""Public, JSON-safe models returned by the recognition SDK."""

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
    physical_paragraph_index: Optional[int]
    physical_occurrence_index: int
    physical_text_sha256: str
    physical_canonical_text_sha256: str
    physical_text_length_utf16: int
    physical_canonical_text_length_utf16: int
    locator_version: str
    segment_index: int
    segment_count: int
    segment_count_total: int
    segment_count_located: int
    segment_count_confirmed: int
    raw_start_utf16: Optional[int]
    raw_end_utf16: Optional[int]
    canonical_start_utf16: Optional[int]
    canonical_end_utf16: Optional[int]
    range_start_utf16: Optional[int]
    range_end_utf16: Optional[int]
    locator_verified: bool
    source_locator_status: str
    source_locator_evidence: Tuple[str, ...]
    source_locator_warnings: Tuple[str, ...]
    kind: str
    type_id: str
    section: str
    text_sha256: str
    text_length_utf16: int
    previous_text_sha256: str
    next_text_sha256: str
    format_role: str
    review_level: str
    classification_confidence: float
    classification_evidence: Tuple[str, ...]
    review_reasons: Tuple[str, ...]
    raw_fragment_sha256: str
    canonical_fragment_sha256: str
    prefix_context_sha256: str
    suffix_context_sha256: str
    segment_format: Dict[str, Any]
    recognized_text: Optional[str] = None
    raw_fragment_text: Optional[str] = None
    canonical_fragment_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        value = {
            "block_index": self.block_index,
            "source_paragraph_index": self.source_paragraph_index,
            "physical_paragraph_index": self.physical_paragraph_index,
            "physical_occurrence_index": self.physical_occurrence_index,
            "physical_text_sha256": self.physical_text_sha256,
            "physical_canonical_text_sha256": self.physical_canonical_text_sha256,
            "physical_text_length_utf16": self.physical_text_length_utf16,
            "physical_canonical_text_length_utf16": self.physical_canonical_text_length_utf16,
            "locator_version": self.locator_version,
            "segment_index": self.segment_index,
            "segment_count": self.segment_count,
            "segment_count_total": self.segment_count_total,
            "segment_count_located": self.segment_count_located,
            "segment_count_confirmed": self.segment_count_confirmed,
            "raw_start_utf16": self.raw_start_utf16,
            "raw_end_utf16": self.raw_end_utf16,
            "canonical_start_utf16": self.canonical_start_utf16,
            "canonical_end_utf16": self.canonical_end_utf16,
            # Compatibility aliases.  These have always been source-text
            # UTF-16 offsets and remain raw offsets in locator v2.
            "range_start_utf16": self.range_start_utf16,
            "range_end_utf16": self.range_end_utf16,
            "range_coordinate_system": "source_raw_text_utf16",
            "offset_encoding": "utf16_code_unit",
            "locator_verified": self.locator_verified,
            "source_locator_status": self.source_locator_status,
            "source_locator_evidence": list(self.source_locator_evidence),
            "source_locator_warnings": list(self.source_locator_warnings),
            "kind": self.kind,
            "type_id": self.type_id,
            "section": self.section,
            "text_sha256": self.text_sha256,
            "text_length_utf16": self.text_length_utf16,
            "previous_text_sha256": self.previous_text_sha256,
            "next_text_sha256": self.next_text_sha256,
            "format_role": self.format_role,
            "review_level": self.review_level,
            "classification_confidence": self.classification_confidence,
            "classification_evidence": list(self.classification_evidence),
            "review_reasons": list(self.review_reasons),
            "raw_fragment_sha256": self.raw_fragment_sha256,
            "canonical_fragment_sha256": self.canonical_fragment_sha256,
            "prefix_context_sha256": self.prefix_context_sha256,
            "suffix_context_sha256": self.suffix_context_sha256,
            "segment_format": dict(self.segment_format),
        }
        if self.recognized_text is not None:
            value["recognized_text"] = self.recognized_text
        if self.raw_fragment_text is not None:
            value["raw_fragment_text"] = self.raw_fragment_text
        if self.canonical_fragment_text is not None:
            value["canonical_fragment_text"] = self.canonical_fragment_text
        return value


@dataclass(frozen=True)
class RecognitionPlan:
    """Versioned, read-only recognition result for a DOCX snapshot."""

    schema_version: str
    engine_version: str
    package_version: str
    locator_version: str
    host_text_contract_version: str
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
            "package_version": self.package_version,
            "locator_version": self.locator_version,
            "host_text_contract_version": self.host_text_contract_version,
            "source_sha256": self.source_sha256,
            "processing_mode": self.processing_mode,
            "recognition_mode": self.recognition_mode,
            "document_mode": self.document_mode,
            "document_mode_confidence": self.document_mode_confidence,
            "blocks": [block.to_dict() for block in self.blocks],
            "review_items": [item.to_dict() for item in self.review_items],
        }


@dataclass(frozen=True)
class HostParagraph:
    """A host-neutral physical paragraph snapshot supplied by an editor."""

    host_paragraph_index: int
    raw_text: str
    story_type: str = "main"
    is_in_table: bool = False


@dataclass(frozen=True)
class HostSnapshot:
    """A local editor snapshot used only to bind an existing recognition plan."""

    host_type: str
    paragraphs: Tuple[HostParagraph, ...]
    document_identity: Optional[str] = None
    text_contract_version: str = "host-text-v1"


@dataclass(frozen=True)
class BoundRecognitionBlock:
    """Verified host-text binding for one block; no editor range is implied."""

    block_index: int
    physical_paragraph_index: Optional[int]
    host_paragraph_index: Optional[int]
    binding_status: str
    binding_confidence: float
    binding_evidence: Tuple[str, ...]
    binding_warnings: Tuple[str, ...]
    host_raw_start_utf16: Optional[int]
    host_raw_end_utf16: Optional[int]
    host_canonical_start_utf16: Optional[int]
    host_canonical_end_utf16: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_index": self.block_index,
            "physical_paragraph_index": self.physical_paragraph_index,
            "host_paragraph_index": self.host_paragraph_index,
            "binding_status": self.binding_status,
            "binding_confidence": self.binding_confidence,
            "binding_evidence": list(self.binding_evidence),
            "binding_warnings": list(self.binding_warnings),
            # These offsets are in host snapshot raw text, not WPS Range.
            "host_raw_start_utf16": self.host_raw_start_utf16,
            "host_raw_end_utf16": self.host_raw_end_utf16,
            "host_canonical_start_utf16": self.host_canonical_start_utf16,
            "host_canonical_end_utf16": self.host_canonical_end_utf16,
            "host_coordinate_system": "host_snapshot_raw_text_utf16",
            "host_canonical_coordinate_system": "host_snapshot_canonical_text_utf16",
        }


@dataclass(frozen=True)
class PhysicalParagraphBinding:
    """Alignment state for one source physical paragraph group."""

    source_physical_paragraph_index: int
    host_paragraph_index: Optional[int]
    status: str
    score: int
    candidate_host_paragraph_indexes: Tuple[int, ...]
    evidence: Tuple[str, ...]
    warnings: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_physical_paragraph_index": self.source_physical_paragraph_index,
            "host_paragraph_index": self.host_paragraph_index,
            "status": self.status,
            "score": self.score,
            "candidate_host_paragraph_indexes": list(self.candidate_host_paragraph_indexes),
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class RecognitionBinding:
    """Result of binding a text-free recognition plan to a local snapshot."""

    locator_version: str
    source_sha256: str
    host_type: str
    document_identity: Optional[str]
    host_text_contract_version: str
    blocks: Tuple[BoundRecognitionBlock, ...]
    physical_paragraphs: Tuple[PhysicalParagraphBinding, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "locator_version": self.locator_version,
            "source_sha256": self.source_sha256,
            "host_type": self.host_type,
            "document_identity": self.document_identity,
            "host_text_contract_version": self.host_text_contract_version,
            "blocks": [block.to_dict() for block in self.blocks],
            "physical_paragraphs": [item.to_dict() for item in self.physical_paragraphs],
        }
