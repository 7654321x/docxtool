"""Public, JSON-safe SDK models for the host-neutral contract."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .constants import (
    HOST_SNAPSHOT_SCHEMA_VERSION,
    HOST_TEXT_CONTRACT_VERSION,
    INTEGRATION_CONTRACT_VERSION,
    OFFSET_ENCODING,
    RECOGNITION_BINDING_SCHEMA_VERSION,
    RECOGNITION_MODES,
    RECOGNITION_PLAN_SCHEMA_VERSION,
    RECOGNITION_REQUEST_SCHEMA_VERSION,
    RECOMMENDED_ACTIONS,
    SDK_MANIFEST_SCHEMA_VERSION,
    SOURCE_LOCATOR_VERSION,
    STORY_TYPES,
    PROCESSING_MODES,
)
from .errors import (
    InvalidHostSnapshotError,
    InvalidRecognitionBindingError,
    InvalidRecognitionPlanError,
    InvalidRequestError,
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: Any) -> str:
    """Create a deterministic, text-free public ID from JSON-safe inputs."""
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "{0}_{1}".format(prefix, _sha256_text(payload)[:32])


def mapping_digest(value: Any) -> str:
    """Return a deterministic digest for options without exposing their content."""
    payload = json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return _sha256_text(payload)


def _tuple_str(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value)


def _optional_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) else None


def _bool(value: Any, default: bool = False) -> bool:
    return bool(default if value is None else value)


def _review_status(level: str, locator_status: str = "confirmed") -> str:
    if locator_status == "unresolved":
        return "unresolved"
    if level in {"review", "critical_review"}:
        return "review"
    return "confirmed"


@dataclass(frozen=True)
class SdkManifest:
    """Text-free SDK capability manifest."""

    schema_version: str
    package_version: str
    integration_contract_versions: Tuple[str, ...]
    recognition_plan_versions: Tuple[str, ...]
    host_snapshot_versions: Tuple[str, ...]
    recognition_binding_versions: Tuple[str, ...]
    source_locator_versions: Tuple[str, ...]
    host_text_contract_versions: Tuple[str, ...]
    offset_encodings: Tuple[str, ...]
    capabilities: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package_version": self.package_version,
            "integration_contract_versions": list(self.integration_contract_versions),
            "recognition_plan_versions": list(self.recognition_plan_versions),
            "host_snapshot_versions": list(self.host_snapshot_versions),
            "recognition_binding_versions": list(self.recognition_binding_versions),
            "source_locator_versions": list(self.source_locator_versions),
            "host_text_contract_versions": list(self.host_text_contract_versions),
            "offset_encodings": list(self.offset_encodings),
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class RecognitionRequest:
    """Versioned recognition request for Python and CLI callers."""

    schema_version: str = RECOGNITION_REQUEST_SCHEMA_VERSION
    processing_mode: str = "structural"
    recognition_mode: str = "authoritative"
    include_text: bool = False
    include_raw_text: bool = False
    format_config: Optional[Mapping[str, Any]] = None
    feature_overrides: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        if self.schema_version != RECOGNITION_REQUEST_SCHEMA_VERSION:
            raise InvalidRequestError(
                "不支持的识别请求版本",
                code="UNSUPPORTED_SCHEMA_VERSION",
                details={"path": "schema_version"},
            )
        if self.processing_mode not in PROCESSING_MODES:
            raise InvalidRequestError("processing_mode 不受支持", details={"path": "processing_mode"})
        if self.recognition_mode not in RECOGNITION_MODES:
            raise InvalidRequestError("recognition_mode 不受支持", details={"path": "recognition_mode"})
        if not isinstance(self.include_text, bool) or not isinstance(self.include_raw_text, bool):
            raise InvalidRequestError("include_text 和 include_raw_text 必须为布尔值")
        if self.include_raw_text and not self.include_text:
            object.__setattr__(self, "include_text", True)
        if self.format_config is not None and not isinstance(self.format_config, Mapping):
            raise InvalidRequestError("format_config 必须是 JSON 对象或 null", details={"path": "format_config"})
        if self.feature_overrides is not None and not isinstance(self.feature_overrides, Mapping):
            raise InvalidRequestError(
                "feature_overrides 必须是 JSON 对象或 null",
                details={"path": "feature_overrides"},
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, strict: bool = False) -> "RecognitionRequest":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("RecognitionRequest 必须是 JSON 对象")
        known = {
            "schema_version",
            "processing_mode",
            "recognition_mode",
            "include_text",
            "include_raw_text",
            "format_config",
            "feature_overrides",
        }
        if strict:
            extra = sorted(set(value) - known)
            if extra:
                raise InvalidRequestError("RecognitionRequest 包含未知字段", details={"path": extra[0]})
        return cls(
            schema_version=str(value.get("schema_version", RECOGNITION_REQUEST_SCHEMA_VERSION)),
            processing_mode=str(value.get("processing_mode", "structural") or "structural"),
            recognition_mode=str(value.get("recognition_mode", "authoritative") or "authoritative"),
            include_text=_bool(value.get("include_text")),
            include_raw_text=_bool(value.get("include_raw_text")),
            format_config=value.get("format_config"),
            feature_overrides=value.get("feature_overrides"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "processing_mode": self.processing_mode,
            "recognition_mode": self.recognition_mode,
            "include_text": self.include_text,
            "include_raw_text": self.include_raw_text,
            "format_config": dict(self.format_config) if self.format_config is not None else None,
            "feature_overrides": dict(self.feature_overrides) if self.feature_overrides is not None else None,
        }

    def digest(self) -> str:
        return mapping_digest(self.to_dict())


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
    block_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_id": self.block_id,
            "block_index": self.block_index,
            "source_paragraph_index": self.source_paragraph_index,
            "final_type": self.final_type,
            "level": self.level,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "evidence": list(self.evidence),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewItem":
        if not isinstance(value, Mapping):
            raise InvalidRecognitionPlanError("review_items[] 必须是 JSON 对象")
        return cls(
            block_id=str(value.get("block_id", "") or ""),
            block_index=int(value.get("block_index", 0) or 0),
            source_paragraph_index=_optional_int(value.get("source_paragraph_index")),
            final_type=str(value.get("final_type", "") or ""),
            level=str(value.get("level", "review") or "review"),
            confidence=float(value.get("confidence", 0.0) or 0.0),
            reasons=_tuple_str(value.get("reasons", ())),
            evidence=_tuple_str(value.get("evidence", ())),
        )


@dataclass(frozen=True)
class RecognitionBlock:
    """One recognized document block with stable source anchors."""

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
    block_id: str = ""
    physical_group_id: str = ""
    recognized_text: Optional[str] = None
    raw_fragment_text: Optional[str] = None
    canonical_fragment_text: Optional[str] = None

    def with_ids(self, plan_id: str) -> "RecognitionBlock":
        physical_group_id = self.physical_group_id or stable_id(
            "pg",
            plan_id,
            self.physical_paragraph_index,
            self.physical_occurrence_index,
            self.physical_text_sha256,
        )
        block_id = self.block_id or stable_id(
            "blk",
            plan_id,
            physical_group_id,
            self.segment_index,
            self.raw_fragment_sha256,
            self.canonical_fragment_sha256,
            self.type_id,
        )
        return RecognitionBlock(
            **{**self.__dict__, "block_id": block_id, "physical_group_id": physical_group_id}
        )

    def to_dict(self) -> Dict[str, Any]:
        classification_status = _review_status(self.review_level, self.source_locator_status)
        source_locator = {
            "status": self.source_locator_status,
            "verified": self.locator_verified,
            "version": self.locator_version,
            "physical_paragraph_index": self.physical_paragraph_index,
            "physical_occurrence_index": self.physical_occurrence_index,
            "physical_raw_text_sha256": self.physical_text_sha256,
            "physical_canonical_text_sha256": self.physical_canonical_text_sha256,
            "physical_text_length_utf16": self.physical_text_length_utf16,
            "physical_canonical_text_length_utf16": self.physical_canonical_text_length_utf16,
            "raw_span": {
                "start": self.raw_start_utf16,
                "end": self.raw_end_utf16,
                "coordinate_system": "source_raw_text",
                "encoding": OFFSET_ENCODING,
            },
            "canonical_span": {
                "start": self.canonical_start_utf16,
                "end": self.canonical_end_utf16,
                "coordinate_system": "source_canonical_text",
                "encoding": OFFSET_ENCODING,
            },
            "raw_fragment_sha256": self.raw_fragment_sha256,
            "canonical_fragment_sha256": self.canonical_fragment_sha256,
            "prefix_context_sha256": self.prefix_context_sha256,
            "suffix_context_sha256": self.suffix_context_sha256,
            "evidence": list(self.source_locator_evidence),
            "warnings": list(self.source_locator_warnings),
        }
        value = {
            "block_id": self.block_id,
            "block_index": self.block_index,
            "physical_group_id": self.physical_group_id,
            "semantic": {
                "kind": self.kind,
                "type_id": self.type_id,
                "section": self.section,
                "format_role": self.format_role,
            },
            "classification": {
                "status": classification_status,
                "confidence": self.classification_confidence,
                "evidence": list(self.classification_evidence),
                "review_level": self.review_level,
                "review_reasons": list(self.review_reasons),
            },
            "segment": {
                "index": self.segment_index,
                "count": self.segment_count,
                "count_total": self.segment_count_total,
                "count_located": self.segment_count_located,
                "count_confirmed": self.segment_count_confirmed,
            },
            "source_locator": source_locator,
            "format_features": dict(self.segment_format),
            "text": {
                "recognized_text": self.recognized_text,
                "raw_fragment_text": self.raw_fragment_text,
                "canonical_fragment_text": self.canonical_fragment_text,
            },
            # Compatibility aliases retained for existing callers.
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
            "range_start_utf16": self.range_start_utf16,
            "range_end_utf16": self.range_end_utf16,
            "range_coordinate_system": "source_raw_text_utf16",
            "offset_encoding": OFFSET_ENCODING,
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

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecognitionBlock":
        if not isinstance(value, Mapping):
            raise InvalidRecognitionPlanError("blocks[] 必须是 JSON 对象")
        semantic = value.get("semantic") if isinstance(value.get("semantic"), Mapping) else {}
        classification = value.get("classification") if isinstance(value.get("classification"), Mapping) else {}
        segment = value.get("segment") if isinstance(value.get("segment"), Mapping) else {}
        locator = value.get("source_locator") if isinstance(value.get("source_locator"), Mapping) else {}
        raw_span = locator.get("raw_span") if isinstance(locator.get("raw_span"), Mapping) else {}
        canonical_span = locator.get("canonical_span") if isinstance(locator.get("canonical_span"), Mapping) else {}
        text = value.get("text") if isinstance(value.get("text"), Mapping) else {}
        return cls(
            block_id=str(value.get("block_id", "") or ""),
            block_index=int(value.get("block_index", 0) or 0),
            physical_group_id=str(value.get("physical_group_id", "") or ""),
            source_paragraph_index=_optional_int(value.get("source_paragraph_index")),
            physical_paragraph_index=_optional_int(
                locator.get("physical_paragraph_index", value.get("physical_paragraph_index"))
            ),
            physical_occurrence_index=int(
                locator.get("physical_occurrence_index", value.get("physical_occurrence_index", 0)) or 0
            ),
            physical_text_sha256=str(
                locator.get("physical_raw_text_sha256", value.get("physical_text_sha256", "")) or ""
            ),
            physical_canonical_text_sha256=str(
                locator.get(
                    "physical_canonical_text_sha256",
                    value.get("physical_canonical_text_sha256", ""),
                )
                or ""
            ),
            physical_text_length_utf16=int(
                locator.get("physical_text_length_utf16", value.get("physical_text_length_utf16", 0)) or 0
            ),
            physical_canonical_text_length_utf16=int(
                locator.get(
                    "physical_canonical_text_length_utf16",
                    value.get("physical_canonical_text_length_utf16", 0),
                )
                or 0
            ),
            locator_version=str(locator.get("version", value.get("locator_version", SOURCE_LOCATOR_VERSION)) or ""),
            segment_index=int(segment.get("index", value.get("segment_index", 0)) or 0),
            segment_count=int(segment.get("count", value.get("segment_count", 0)) or 0),
            segment_count_total=int(segment.get("count_total", value.get("segment_count_total", 0)) or 0),
            segment_count_located=int(segment.get("count_located", value.get("segment_count_located", 0)) or 0),
            segment_count_confirmed=int(segment.get("count_confirmed", value.get("segment_count_confirmed", 0)) or 0),
            raw_start_utf16=_optional_int(raw_span.get("start", value.get("raw_start_utf16"))),
            raw_end_utf16=_optional_int(raw_span.get("end", value.get("raw_end_utf16"))),
            canonical_start_utf16=_optional_int(canonical_span.get("start", value.get("canonical_start_utf16"))),
            canonical_end_utf16=_optional_int(canonical_span.get("end", value.get("canonical_end_utf16"))),
            range_start_utf16=_optional_int(value.get("range_start_utf16", raw_span.get("start"))),
            range_end_utf16=_optional_int(value.get("range_end_utf16", raw_span.get("end"))),
            locator_verified=bool(locator.get("verified", value.get("locator_verified", False))),
            source_locator_status=str(locator.get("status", value.get("source_locator_status", "unresolved")) or ""),
            source_locator_evidence=_tuple_str(locator.get("evidence", value.get("source_locator_evidence", ()))),
            source_locator_warnings=_tuple_str(locator.get("warnings", value.get("source_locator_warnings", ()))),
            kind=str(semantic.get("kind", value.get("kind", "paragraph")) or ""),
            type_id=str(semantic.get("type_id", value.get("type_id", "unknown")) or ""),
            section=str(semantic.get("section", value.get("section", "body")) or ""),
            text_sha256=str(value.get("text_sha256", "") or ""),
            text_length_utf16=int(value.get("text_length_utf16", 0) or 0),
            previous_text_sha256=str(value.get("previous_text_sha256", "") or ""),
            next_text_sha256=str(value.get("next_text_sha256", "") or ""),
            format_role=str(semantic.get("format_role", value.get("format_role", "body")) or ""),
            review_level=str(classification.get("review_level", value.get("review_level", "confirmed")) or ""),
            classification_confidence=float(
                classification.get("confidence", value.get("classification_confidence", 0.0)) or 0.0
            ),
            classification_evidence=_tuple_str(
                classification.get("evidence", value.get("classification_evidence", ()))
            ),
            review_reasons=_tuple_str(
                classification.get("review_reasons", value.get("review_reasons", ()))
            ),
            raw_fragment_sha256=str(
                locator.get("raw_fragment_sha256", value.get("raw_fragment_sha256", "")) or ""
            ),
            canonical_fragment_sha256=str(
                locator.get("canonical_fragment_sha256", value.get("canonical_fragment_sha256", "")) or ""
            ),
            prefix_context_sha256=str(
                locator.get("prefix_context_sha256", value.get("prefix_context_sha256", "")) or ""
            ),
            suffix_context_sha256=str(
                locator.get("suffix_context_sha256", value.get("suffix_context_sha256", "")) or ""
            ),
            segment_format=dict(value.get("format_features", value.get("segment_format", {})) or {}),
            recognized_text=text.get("recognized_text", value.get("recognized_text")),
            raw_fragment_text=text.get("raw_fragment_text", value.get("raw_fragment_text")),
            canonical_fragment_text=text.get("canonical_fragment_text", value.get("canonical_fragment_text")),
        )


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
    plan_id: str = ""
    integration_contract_version: str = INTEGRATION_CONTRACT_VERSION
    request_digest: str = ""
    source_media_type: str = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    text_included: bool = False
    raw_text_included: bool = False

    def __post_init__(self) -> None:
        plan_id = self.plan_id or stable_id(
            "plan",
            self.source_sha256,
            self.integration_contract_version,
            self.schema_version,
            self.processing_mode,
            self.recognition_mode,
            self.request_digest,
        )
        blocks = tuple(block.with_ids(plan_id) for block in self.blocks)
        review_by_block_index = {item.block_index: item for item in self.review_items}
        review_items = []
        for item in self.review_items:
            block = blocks[item.block_index] if 0 <= item.block_index < len(blocks) else None
            review_items.append(
                ReviewItem(
                    block_id=item.block_id or (block.block_id if block else ""),
                    block_index=item.block_index,
                    source_paragraph_index=item.source_paragraph_index,
                    final_type=item.final_type,
                    level=item.level,
                    confidence=item.confidence,
                    reasons=item.reasons,
                    evidence=item.evidence,
                )
            )
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "blocks", blocks)
        if review_by_block_index:
            object.__setattr__(self, "review_items", tuple(review_items))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "integration_contract_version": self.integration_contract_version,
            "plan_id": self.plan_id,
            "producer": {
                "package_version": self.package_version,
                "engine_version": self.engine_version,
            },
            "source": {
                "media_type": self.source_media_type,
                "sha256": self.source_sha256,
                "text_included": self.text_included,
                "raw_text_included": self.raw_text_included,
            },
            "contracts": {
                "source_locator_version": self.locator_version,
                "host_text_contract_version": self.host_text_contract_version,
                "offset_encoding": OFFSET_ENCODING,
            },
            "recognition": {
                "processing_mode": self.processing_mode,
                "recognition_mode": self.recognition_mode,
                "document_mode": self.document_mode,
                "document_mode_confidence": self.document_mode_confidence,
                "request_digest": self.request_digest,
            },
            "blocks": [block.to_dict() for block in self.blocks],
            "review_items": [item.to_dict() for item in self.review_items],
            # Compatibility aliases retained for existing callers.
            "engine_version": self.engine_version,
            "package_version": self.package_version,
            "locator_version": self.locator_version,
            "host_text_contract_version": self.host_text_contract_version,
            "source_sha256": self.source_sha256,
            "processing_mode": self.processing_mode,
            "recognition_mode": self.recognition_mode,
            "document_mode": self.document_mode,
            "document_mode_confidence": self.document_mode_confidence,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, strict: bool = False) -> "RecognitionPlan":
        if not isinstance(value, Mapping):
            raise InvalidRecognitionPlanError("RecognitionPlan 必须是 JSON 对象")
        if strict and value.get("schema_version") != RECOGNITION_PLAN_SCHEMA_VERSION:
            raise InvalidRecognitionPlanError(
                "不支持的 RecognitionPlan 版本",
                code="UNSUPPORTED_SCHEMA_VERSION",
                details={"path": "schema_version"},
            )
        producer = value.get("producer") if isinstance(value.get("producer"), Mapping) else {}
        source = value.get("source") if isinstance(value.get("source"), Mapping) else {}
        contracts = value.get("contracts") if isinstance(value.get("contracts"), Mapping) else {}
        recognition = value.get("recognition") if isinstance(value.get("recognition"), Mapping) else {}
        blocks_value = value.get("blocks")
        if not isinstance(blocks_value, Sequence) or isinstance(blocks_value, (str, bytes)):
            raise InvalidRecognitionPlanError("RecognitionPlan.blocks 必须是数组", details={"path": "blocks"})
        blocks = tuple(RecognitionBlock.from_dict(item) for item in blocks_value)
        review_items = tuple(
            ReviewItem.from_dict(item)
            for item in value.get("review_items", ())
            if isinstance(item, Mapping)
        )
        return cls(
            schema_version=str(value.get("schema_version", RECOGNITION_PLAN_SCHEMA_VERSION) or ""),
            integration_contract_version=str(
                value.get("integration_contract_version", INTEGRATION_CONTRACT_VERSION) or ""
            ),
            plan_id=str(value.get("plan_id", "") or ""),
            engine_version=str(producer.get("engine_version", value.get("engine_version", "")) or ""),
            package_version=str(producer.get("package_version", value.get("package_version", "")) or ""),
            locator_version=str(
                contracts.get("source_locator_version", value.get("locator_version", SOURCE_LOCATOR_VERSION)) or ""
            ),
            host_text_contract_version=str(
                contracts.get(
                    "host_text_contract_version",
                    value.get("host_text_contract_version", HOST_TEXT_CONTRACT_VERSION),
                )
                or ""
            ),
            source_sha256=str(source.get("sha256", value.get("source_sha256", "")) or ""),
            source_media_type=str(
                source.get(
                    "media_type",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
                or ""
            ),
            text_included=bool(source.get("text_included", False)),
            raw_text_included=bool(source.get("raw_text_included", False)),
            processing_mode=str(recognition.get("processing_mode", value.get("processing_mode", "")) or ""),
            recognition_mode=str(recognition.get("recognition_mode", value.get("recognition_mode", "")) or ""),
            document_mode=str(recognition.get("document_mode", value.get("document_mode", "unknown")) or ""),
            document_mode_confidence=float(
                recognition.get(
                    "document_mode_confidence",
                    value.get("document_mode_confidence", 0.0),
                )
                or 0.0
            ),
            request_digest=str(recognition.get("request_digest", value.get("request_digest", "")) or ""),
            blocks=blocks,
            review_items=review_items,
        )


@dataclass(frozen=True)
class HostParagraph:
    """A host-neutral physical paragraph snapshot supplied by an editor."""

    host_paragraph_index: int
    raw_text: str
    story_type: str = "main"
    is_in_table: bool = False
    host_paragraph_id: str = ""
    story_id: str = "main"
    story_paragraph_index: Optional[int] = None
    section_index: Optional[int] = None

    def __post_init__(self) -> None:
        host_id = self.host_paragraph_id or "{0}:{1:06d}".format(
            self.story_id or "main",
            self.host_paragraph_index,
        )
        story_index = self.story_paragraph_index
        if story_index is None:
            story_index = self.host_paragraph_index
        object.__setattr__(self, "host_paragraph_id", host_id)
        object.__setattr__(self, "story_paragraph_index", story_index)
        if self.story_type not in STORY_TYPES:
            object.__setattr__(self, "story_type", "unknown")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host_paragraph_id": self.host_paragraph_id,
            "host_paragraph_index": self.host_paragraph_index,
            "story_id": self.story_id,
            "story_type": self.story_type,
            "story_paragraph_index": self.story_paragraph_index,
            "section_index": self.section_index,
            "is_in_table": self.is_in_table,
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], ordinal: int) -> "HostParagraph":
        if not isinstance(value, Mapping) or not isinstance(value.get("raw_text"), str):
            raise InvalidHostSnapshotError(
                "每个 host paragraph 必须包含 raw_text 字符串",
                details={"path": "paragraphs[{0}].raw_text".format(ordinal)},
            )
        index = value.get("host_paragraph_index", ordinal)
        if not isinstance(index, int) or index < 0:
            raise InvalidHostSnapshotError(
                "host_paragraph_index 必须为非负整数",
                details={"path": "paragraphs[{0}].host_paragraph_index".format(ordinal)},
            )
        return cls(
            host_paragraph_id=str(value.get("host_paragraph_id", "") or ""),
            host_paragraph_index=index,
            raw_text=value["raw_text"],
            story_id=str(value.get("story_id", "main") or "main"),
            story_type=str(value.get("story_type", "main") or "main"),
            story_paragraph_index=_optional_int(value.get("story_paragraph_index")),
            section_index=_optional_int(value.get("section_index")),
            is_in_table=bool(value.get("is_in_table", False)),
        )


@dataclass(frozen=True)
class HostSnapshot:
    """A local editor snapshot used only to bind an existing recognition plan."""

    host_type: str
    paragraphs: Tuple[HostParagraph, ...]
    document_identity: Optional[str] = None
    text_contract_version: str = HOST_TEXT_CONTRACT_VERSION
    schema_version: str = HOST_SNAPSHOT_SCHEMA_VERSION
    integration_contract_version: str = INTEGRATION_CONTRACT_VERSION
    snapshot_id: str = ""
    document_revision: Optional[str] = None
    host_version: Optional[str] = None
    host_platform: Optional[str] = None
    offset_encoding: str = OFFSET_ENCODING

    def __post_init__(self) -> None:
        snapshot_id = self.snapshot_id or stable_id(
            "snap",
            self.host_type,
            self.document_identity,
            self.document_revision,
            [
                (
                    item.host_paragraph_id,
                    item.host_paragraph_index,
                    item.story_id,
                    item.story_type,
                    _sha256_text(item.raw_text),
                )
                for item in self.paragraphs
            ],
        )
        object.__setattr__(self, "snapshot_id", snapshot_id)

    def to_dict(self, *, include_text: bool = True) -> Dict[str, Any]:
        paragraphs = []
        for item in self.paragraphs:
            payload = item.to_dict()
            if not include_text:
                payload["raw_text"] = None
                payload["raw_text_sha256"] = _sha256_text(item.raw_text)
            paragraphs.append(payload)
        return {
            "schema_version": self.schema_version,
            "integration_contract_version": self.integration_contract_version,
            "snapshot_id": self.snapshot_id,
            "document_identity": self.document_identity,
            "document_revision": self.document_revision,
            "host": {
                "kind": self.host_type,
                "version": self.host_version,
                "platform": self.host_platform,
            },
            "host_type": self.host_type,
            "text_contract_version": self.text_contract_version,
            "offset_encoding": self.offset_encoding,
            "paragraphs": paragraphs,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        strict: bool = False,
        allow_legacy: bool = True,
    ) -> "HostSnapshot":
        if isinstance(value, HostSnapshot):
            return value
        if not isinstance(value, Mapping):
            raise InvalidHostSnapshotError("HostSnapshot 必须是 JSON 对象")
        schema_version = str(value.get("schema_version", HOST_SNAPSHOT_SCHEMA_VERSION) or "")
        if strict and schema_version != HOST_SNAPSHOT_SCHEMA_VERSION:
            raise InvalidHostSnapshotError(
                "不支持的 HostSnapshot 版本",
                code="UNSUPPORTED_SCHEMA_VERSION",
                details={"path": "schema_version"},
            )
        if strict and not value.get("snapshot_id"):
            raise InvalidHostSnapshotError("snapshot_id 不能为空", details={"path": "snapshot_id"})
        if not allow_legacy and not value.get("snapshot_id"):
            raise InvalidHostSnapshotError("snapshot_id 不能为空", details={"path": "snapshot_id"})
        host = value.get("host") if isinstance(value.get("host"), Mapping) else {}
        host_type = str(host.get("kind", value.get("host_type", "unknown")) or "")
        if not host_type:
            raise InvalidHostSnapshotError("host.kind 必须为非空字符串", details={"path": "host.kind"})
        paragraphs_value = value.get("paragraphs")
        if not isinstance(paragraphs_value, Sequence) or isinstance(paragraphs_value, (str, bytes)):
            raise InvalidHostSnapshotError("host_snapshot.paragraphs 必须为段落数组", details={"path": "paragraphs"})
        paragraphs = tuple(HostParagraph.from_dict(item, ordinal) for ordinal, item in enumerate(paragraphs_value))
        ids = [item.host_paragraph_id for item in paragraphs]
        indexes = [item.host_paragraph_index for item in paragraphs]
        if len(ids) != len(set(ids)):
            raise InvalidHostSnapshotError("host_paragraph_id 不能重复", details={"path": "paragraphs"})
        if len(indexes) != len(set(indexes)):
            raise InvalidHostSnapshotError("host_paragraph_index 不能重复", details={"path": "paragraphs"})
        contract = str(value.get("text_contract_version", HOST_TEXT_CONTRACT_VERSION) or "")
        offset_encoding = str(value.get("offset_encoding", OFFSET_ENCODING) or "")
        return cls(
            schema_version=schema_version,
            integration_contract_version=str(
                value.get("integration_contract_version", INTEGRATION_CONTRACT_VERSION) or ""
            ),
            snapshot_id=str(value.get("snapshot_id", "") or ""),
            document_identity=(
                str(value.get("document_identity")) if value.get("document_identity") is not None else None
            ),
            document_revision=(
                str(value.get("document_revision")) if value.get("document_revision") is not None else None
            ),
            host_type=host_type,
            host_version=str(host.get("version")) if host.get("version") is not None else None,
            host_platform=str(host.get("platform")) if host.get("platform") is not None else None,
            text_contract_version=contract,
            offset_encoding=offset_encoding,
            paragraphs=paragraphs,
        )


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
    block_id: str = ""
    physical_group_id: str = ""
    host_paragraph_id: Optional[str] = None
    story_id: Optional[str] = None
    story_type: Optional[str] = None
    recommended_action: str = "skip"
    preconditions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        recommended_action = self.recommended_action
        if recommended_action not in RECOMMENDED_ACTIONS:
            recommended_action = "skip"
        value = {
            "block_id": self.block_id,
            "block_index": self.block_index,
            "physical_group_id": self.physical_group_id,
            "binding": {
                "status": self.binding_status,
                "confidence": self.binding_confidence,
                "evidence": list(self.binding_evidence),
                "warnings": list(self.binding_warnings),
                "recommended_action": recommended_action,
            },
            "host_target": {
                "host_paragraph_id": self.host_paragraph_id,
                "host_paragraph_index": self.host_paragraph_index,
                "story_id": self.story_id,
                "story_type": self.story_type,
                "raw_span": {
                    "start": self.host_raw_start_utf16,
                    "end": self.host_raw_end_utf16,
                    "coordinate_system": "host_snapshot_raw_text",
                    "encoding": OFFSET_ENCODING,
                },
                "canonical_span": {
                    "start": self.host_canonical_start_utf16,
                    "end": self.host_canonical_end_utf16,
                    "coordinate_system": "host_snapshot_canonical_text",
                    "encoding": OFFSET_ENCODING,
                },
            },
            "preconditions": dict(self.preconditions),
            # Compatibility aliases retained for existing callers.
            "physical_paragraph_index": self.physical_paragraph_index,
            "host_paragraph_index": self.host_paragraph_index,
            "binding_status": self.binding_status,
            "binding_confidence": self.binding_confidence,
            "binding_evidence": list(self.binding_evidence),
            "binding_warnings": list(self.binding_warnings),
            "host_raw_start_utf16": self.host_raw_start_utf16,
            "host_raw_end_utf16": self.host_raw_end_utf16,
            "host_canonical_start_utf16": self.host_canonical_start_utf16,
            "host_canonical_end_utf16": self.host_canonical_end_utf16,
            "host_coordinate_system": "host_snapshot_raw_text_utf16",
            "host_canonical_coordinate_system": "host_snapshot_canonical_text_utf16",
        }
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundRecognitionBlock":
        if not isinstance(value, Mapping):
            raise InvalidRecognitionBindingError("binding.blocks[] 必须是 JSON 对象")
        binding = value.get("binding") if isinstance(value.get("binding"), Mapping) else {}
        target = value.get("host_target") if isinstance(value.get("host_target"), Mapping) else {}
        raw_span = target.get("raw_span") if isinstance(target.get("raw_span"), Mapping) else {}
        canonical_span = target.get("canonical_span") if isinstance(target.get("canonical_span"), Mapping) else {}
        return cls(
            block_id=str(value.get("block_id", "") or ""),
            block_index=int(value.get("block_index", 0) or 0),
            physical_group_id=str(value.get("physical_group_id", "") or ""),
            physical_paragraph_index=_optional_int(value.get("physical_paragraph_index")),
            host_paragraph_index=_optional_int(target.get("host_paragraph_index", value.get("host_paragraph_index"))),
            host_paragraph_id=(
                str(target.get("host_paragraph_id"))
                if target.get("host_paragraph_id") is not None
                else None
            ),
            story_id=str(target.get("story_id")) if target.get("story_id") is not None else None,
            story_type=str(target.get("story_type")) if target.get("story_type") is not None else None,
            binding_status=str(binding.get("status", value.get("binding_status", "unresolved")) or ""),
            binding_confidence=float(binding.get("confidence", value.get("binding_confidence", 0.0)) or 0.0),
            binding_evidence=_tuple_str(binding.get("evidence", value.get("binding_evidence", ()))),
            binding_warnings=_tuple_str(binding.get("warnings", value.get("binding_warnings", ()))),
            recommended_action=str(binding.get("recommended_action", value.get("recommended_action", "skip")) or ""),
            host_raw_start_utf16=_optional_int(raw_span.get("start", value.get("host_raw_start_utf16"))),
            host_raw_end_utf16=_optional_int(raw_span.get("end", value.get("host_raw_end_utf16"))),
            host_canonical_start_utf16=_optional_int(
                canonical_span.get("start", value.get("host_canonical_start_utf16"))
            ),
            host_canonical_end_utf16=_optional_int(
                canonical_span.get("end", value.get("host_canonical_end_utf16"))
            ),
            preconditions=dict(value.get("preconditions", {}) or {}),
        )


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
    physical_group_id: str = ""
    host_paragraph_id: Optional[str] = None
    candidate_host_paragraph_ids: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "physical_group_id": self.physical_group_id,
            "source_physical_paragraph_index": self.source_physical_paragraph_index,
            "host_paragraph_id": self.host_paragraph_id,
            "host_paragraph_index": self.host_paragraph_index,
            "status": self.status,
            "score": self.score,
            "candidate_host_paragraph_ids": list(self.candidate_host_paragraph_ids),
            "candidate_host_paragraph_indexes": list(self.candidate_host_paragraph_indexes),
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PhysicalParagraphBinding":
        if not isinstance(value, Mapping):
            raise InvalidRecognitionBindingError("physical_paragraphs[] 必须是 JSON 对象")
        return cls(
            physical_group_id=str(value.get("physical_group_id", "") or ""),
            source_physical_paragraph_index=int(value.get("source_physical_paragraph_index", 0) or 0),
            host_paragraph_id=(
                str(value.get("host_paragraph_id")) if value.get("host_paragraph_id") is not None else None
            ),
            host_paragraph_index=_optional_int(value.get("host_paragraph_index")),
            status=str(value.get("status", "unresolved") or ""),
            score=int(value.get("score", 0) or 0),
            candidate_host_paragraph_ids=tuple(str(item) for item in value.get("candidate_host_paragraph_ids", ())),
            candidate_host_paragraph_indexes=tuple(
                int(item) for item in value.get("candidate_host_paragraph_indexes", ())
            ),
            evidence=_tuple_str(value.get("evidence", ())),
            warnings=_tuple_str(value.get("warnings", ())),
        )


@dataclass(frozen=True)
class RecognitionBinding:
    """Result of binding a recognition plan to a local host snapshot."""

    locator_version: str
    source_sha256: str
    host_type: str
    document_identity: Optional[str]
    host_text_contract_version: str
    blocks: Tuple[BoundRecognitionBlock, ...]
    physical_paragraphs: Tuple[PhysicalParagraphBinding, ...]
    schema_version: str = RECOGNITION_BINDING_SCHEMA_VERSION
    integration_contract_version: str = INTEGRATION_CONTRACT_VERSION
    binding_id: str = ""
    plan_id: str = ""
    snapshot_id: str = ""
    document_revision: Optional[str] = None
    offset_encoding: str = OFFSET_ENCODING

    def __post_init__(self) -> None:
        binding_id = self.binding_id or stable_id(
            "bind",
            self.plan_id,
            self.snapshot_id,
            self.source_sha256,
            self.document_identity,
            self.document_revision,
            [(item.block_id, item.binding_status, item.host_paragraph_id) for item in self.blocks],
        )
        object.__setattr__(self, "binding_id", binding_id)

    def summary(self) -> Dict[str, int]:
        confirmed = sum(1 for item in self.blocks if item.binding_status == "confirmed")
        review = sum(1 for item in self.blocks if item.binding_status == "review")
        unresolved = sum(1 for item in self.blocks if item.binding_status == "unresolved")
        complete_groups = sum(
            1 for item in self.physical_paragraphs if item.status in {"matched_unique", "matched_review"}
        )
        incomplete_groups = len(self.physical_paragraphs) - complete_groups
        return {
            "total_blocks": len(self.blocks),
            "confirmed_blocks": confirmed,
            "review_blocks": review,
            "unresolved_blocks": unresolved,
            "complete_physical_groups": complete_groups,
            "incomplete_physical_groups": incomplete_groups,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "integration_contract_version": self.integration_contract_version,
            "binding_id": self.binding_id,
            "plan_id": self.plan_id,
            "snapshot_id": self.snapshot_id,
            "source_sha256": self.source_sha256,
            "document_identity": self.document_identity,
            "document_revision": self.document_revision,
            "host": {"kind": self.host_type},
            "host_type": self.host_type,
            "contracts": {
                "source_locator_version": self.locator_version,
                "host_text_contract_version": self.host_text_contract_version,
                "offset_encoding": self.offset_encoding,
            },
            "summary": self.summary(),
            "physical_paragraphs": [item.to_dict() for item in self.physical_paragraphs],
            "blocks": [block.to_dict() for block in self.blocks],
            # Compatibility aliases retained for existing callers.
            "locator_version": self.locator_version,
            "host_text_contract_version": self.host_text_contract_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, strict: bool = False) -> "RecognitionBinding":
        if not isinstance(value, Mapping):
            raise InvalidRecognitionBindingError("RecognitionBinding 必须是 JSON 对象")
        if strict and value.get("schema_version") != RECOGNITION_BINDING_SCHEMA_VERSION:
            raise InvalidRecognitionBindingError(
                "不支持的 RecognitionBinding 版本",
                code="UNSUPPORTED_SCHEMA_VERSION",
                details={"path": "schema_version"},
            )
        host = value.get("host") if isinstance(value.get("host"), Mapping) else {}
        contracts = value.get("contracts") if isinstance(value.get("contracts"), Mapping) else {}
        blocks_value = value.get("blocks")
        if not isinstance(blocks_value, Sequence) or isinstance(blocks_value, (str, bytes)):
            raise InvalidRecognitionBindingError("RecognitionBinding.blocks 必须是数组", details={"path": "blocks"})
        physical_value = value.get("physical_paragraphs", ())
        if not isinstance(physical_value, Sequence) or isinstance(physical_value, (str, bytes)):
            raise InvalidRecognitionBindingError(
                "RecognitionBinding.physical_paragraphs 必须是数组",
                details={"path": "physical_paragraphs"},
            )
        return cls(
            schema_version=str(value.get("schema_version", RECOGNITION_BINDING_SCHEMA_VERSION) or ""),
            integration_contract_version=str(
                value.get("integration_contract_version", INTEGRATION_CONTRACT_VERSION) or ""
            ),
            binding_id=str(value.get("binding_id", "") or ""),
            plan_id=str(value.get("plan_id", "") or ""),
            snapshot_id=str(value.get("snapshot_id", "") or ""),
            source_sha256=str(value.get("source_sha256", "") or ""),
            document_identity=(
                str(value.get("document_identity")) if value.get("document_identity") is not None else None
            ),
            document_revision=(
                str(value.get("document_revision")) if value.get("document_revision") is not None else None
            ),
            host_type=str(host.get("kind", value.get("host_type", "unknown")) or ""),
            locator_version=str(
                contracts.get("source_locator_version", value.get("locator_version", SOURCE_LOCATOR_VERSION)) or ""
            ),
            host_text_contract_version=str(
                contracts.get(
                    "host_text_contract_version",
                    value.get("host_text_contract_version", HOST_TEXT_CONTRACT_VERSION),
                )
                or ""
            ),
            offset_encoding=str(contracts.get("offset_encoding", OFFSET_ENCODING) or ""),
            physical_paragraphs=tuple(PhysicalParagraphBinding.from_dict(item) for item in physical_value),
            blocks=tuple(BoundRecognitionBlock.from_dict(item) for item in blocks_value),
        )


def recognition_plan_from_dict(value: Mapping[str, Any], *, strict: bool = False) -> RecognitionPlan:
    return RecognitionPlan.from_dict(value, strict=strict)


def host_snapshot_from_dict(
    value: Mapping[str, Any],
    *,
    strict: bool = False,
    allow_legacy: bool = True,
) -> HostSnapshot:
    return HostSnapshot.from_dict(value, strict=strict, allow_legacy=allow_legacy)


def recognition_binding_from_dict(value: Mapping[str, Any], *, strict: bool = False) -> RecognitionBinding:
    return RecognitionBinding.from_dict(value, strict=strict)
