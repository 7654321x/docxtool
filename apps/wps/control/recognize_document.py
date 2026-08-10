"""Recognition and host-binding adapters for WPS preview.

The saved DOCX produces a DocxTool ``RecognitionPlan``. WPS must then submit a
fresh host snapshot and use ``bind_recognition_plan`` before any editor Range
is created. This module contains no WPS Range math and no duplicate matching
rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Dict, List, Mapping, Optional
import uuid

from docxtool.sdk import RecognitionPlan, bind_recognition_plan, recognize_docx

from .logging_adapter import document_log_context, file_identity, log_event


@dataclass(frozen=True)
class RecognitionSession:
    plan: RecognitionPlan
    public_result: Dict[str, Any]


def recognize_document(
    source_path: str,
    *,
    log_dir: Path,
    format_config: Optional[dict] = None,
    request_id: str = "",
) -> RecognitionSession:
    """Create one authoritative recognition plan for a saved DOCX snapshot."""
    source = Path(source_path).expanduser().resolve()
    if source.suffix.lower() != ".docx" or not source.is_file():
        log_event(
            "ERROR",
            "preview",
            "recognition.input.invalid",
            "WPS 识别输入不是可读 DOCX",
            {
                "request_id": request_id,
                "file_id": file_identity(source),
                "error_code": "INVALID_DOCX_INPUT",
            },
        )
        raise ValueError("INVALID_DOCX_INPUT")
    operation_id = uuid.uuid4().hex
    with document_log_context(source, log_dir, operation_id, request_id) as log_path:
        started_at = time.monotonic()
        log_event(
            "INFO",
            "preview",
            "recognition.start",
            "开始 WPS 预览识别",
            {"operation_id_short": operation_id[:12], "request_id": request_id, "file_id": file_identity(source)},
        )
        try:
            plan = recognize_docx(
                source,
                processing_mode="structural",
                recognition_mode="authoritative",
                format_config=format_config,
                include_text=False,
                include_raw_text=False,
            )
        except Exception as exc:
            log_event(
                "ERROR",
                "preview",
                "recognition.pipeline.failed",
                "DocxTool authoritative 识别失败",
                {
                    "operation_id_short": operation_id[:12],
                    "request_id": request_id,
                    "file_id": file_identity(source),
                    "stage": "authoritative_recognition",
                    "error_code": "WPS_RECOGNITION_PIPELINE_FAILED",
                    "error_type": type(exc).__name__,
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                },
            )
            raise RuntimeError("WPS_RECOGNITION_PIPELINE_FAILED") from exc
        review_count = sum(
            1
            for block in plan.blocks
            if block.review_level in {"review", "critical_review"}
        )
        unresolved_count = sum(1 for block in plan.blocks if not block.locator_verified)
        result = {
            "operation_id": operation_id,
            "plan_id": plan.plan_id,
            "document_mode": plan.document_mode,
            "document_mode_confidence": plan.document_mode_confidence,
            "block_count": len(plan.blocks),
            "review_count": review_count,
            "unresolved_count": unresolved_count,
            "log_file": Path(log_path).name,
        }
        log_event(
            "INFO",
            "preview",
            "recognition.completed",
            "WPS 预览识别完成，等待宿主快照绑定",
            {
                "operation_id_short": operation_id[:12],
                "request_id": request_id,
                "plan_id_short": plan.plan_id[:12],
                "blocks": len(plan.blocks),
                "review": review_count,
                "unresolved": unresolved_count,
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            },
        )
        return RecognitionSession(plan=plan, public_result=result)


def bind_preview(
    plan: RecognitionPlan,
    host_snapshot: Mapping[str, Any],
    *,
    request_id: str = "",
) -> Dict[str, Any]:
    """Bind a plan to the current WPS snapshot and return text-free ranges.

    ``bind_recognition_plan`` intentionally defaults to normal validation.  Do
    not enable ``strict=True`` here: RecognitionPlan/HostSnapshot serializers
    retain documented compatibility aliases, while strict schema mode rejects
    unknown compatibility fields.  Normal Binder validation still verifies the
    SDK/schema contract versions, locator/text contracts, offset encoding,
    paragraph alignment, hashes and per-range preconditions before a block can
    become ``confirmed``.
    """
    started_at = time.monotonic()
    log_event(
        "INFO",
        "preview",
        "binding.start",
        "开始将识别计划绑定到 WPS 宿主快照",
        {
            "request_id": request_id,
            "plan_id_short": plan.plan_id[:12],
            "blocks": len(plan.blocks),
        },
    )
    try:
        binding = bind_recognition_plan(plan, host_snapshot)
    except Exception as exc:
        log_event(
            "ERROR",
            "preview",
            "binding.sdk.failed",
            "SDK HostSnapshot 绑定失败",
            {
                "request_id": request_id,
                "plan_id_short": plan.plan_id[:12],
                "stage": "sdk_binding",
                "error_code": "WPS_BINDING_SDK_FAILED",
                "error_type": type(exc).__name__,
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            },
        )
        raise RuntimeError("WPS_BINDING_SDK_FAILED") from exc
    source_by_id = {block.block_id: block for block in plan.blocks}
    items: List[Dict[str, Any]] = []
    for bound in binding.blocks:
        source = source_by_id.get(bound.block_id)
        if source is None:
            log_event(
                "ERROR",
                "preview",
                "binding.block_missing",
                "绑定结果引用了识别计划中不存在的块",
                {
                    "request_id": request_id,
                    "plan_id_short": plan.plan_id[:12],
                    "block_index": bound.block_index,
                    "error_code": "WPS_PREVIEW_BINDING_BLOCK_MISSING",
                },
            )
            raise ValueError("WPS_PREVIEW_BINDING_BLOCK_MISSING")
        preconditions = dict(bound.preconditions or {})
        items.append(
            {
                "block_id": bound.block_id,
                "block_index": bound.block_index,
                "type_id": source.type_id,
                "format_role": source.format_role,
                "review_level": source.review_level,
                "confidence": source.classification_confidence,
                "segment_index": source.segment_index,
                "segment_count": source.segment_count,
                "binding_status": bound.binding_status,
                "binding_confidence": bound.binding_confidence,
                "binding_warnings": list(bound.binding_warnings),
                "recommended_action": bound.recommended_action,
                "preview_eligible": (
                    (
                        bound.binding_status == "confirmed"
                        and bound.recommended_action == "verify_host_range"
                    )
                    or (
                        bound.binding_status == "review"
                        and bound.recommended_action == "preview_only"
                    )
                ),
                "host_paragraph_index": bound.host_paragraph_index,
                "host_paragraph_id": bound.host_paragraph_id,
                "host_raw_start_utf16": bound.host_raw_start_utf16,
                "host_raw_end_utf16": bound.host_raw_end_utf16,
                "host_paragraph_raw_sha256": preconditions.get(
                    "host_paragraph_raw_sha256", ""
                ),
                "raw_fragment_sha256": preconditions.get("raw_fragment_sha256", ""),
            }
        )
        log_event(
            "DEBUG",
            "preview",
            "binding.item",
            "WPS 绑定项已裁决",
            {
                "request_id": request_id,
                "plan_id_short": plan.plan_id[:12],
                "block_index": bound.block_index,
                "type_id": source.type_id,
                "physical_paragraph_index": source.physical_paragraph_index,
                "physical_occurrence_index": source.physical_occurrence_index,
                "physical_text_length_utf16": source.physical_text_length_utf16,
                "segment_index": source.segment_index,
                "segment_count": source.segment_count,
                "locator_verified": source.locator_verified,
                "locator_status": source.source_locator_status,
                "binding_status": bound.binding_status,
                "recommended_action": bound.recommended_action,
                "warning_count": len(bound.binding_warnings),
            },
        )
        for warning_code in bound.binding_warnings:
            log_event(
                "DEBUG",
                "preview",
                "binding.item.warning",
                "WPS 绑定项包含定位警告",
                {
                    "request_id": request_id,
                    "plan_id_short": plan.plan_id[:12],
                    "block_index": bound.block_index,
                    "type_id": source.type_id,
                    "physical_paragraph_index": source.physical_paragraph_index,
                    "physical_occurrence_index": source.physical_occurrence_index,
                    "physical_text_length_utf16": source.physical_text_length_utf16,
                    "segment_index": source.segment_index,
                    "segment_count": source.segment_count,
                    "locator_verified": source.locator_verified,
                    "locator_status": source.source_locator_status,
                    "binding_status": bound.binding_status,
                    "warning_code": warning_code,
                },
            )
    confirmed_count = sum(1 for item in items if item["binding_status"] == "confirmed")
    review_binding_count = sum(1 for item in items if item["binding_status"] == "review")
    unresolved_binding_count = sum(
        1 for item in items if item["binding_status"] == "unresolved"
    )
    preview_eligible_count = sum(1 for item in items if item["preview_eligible"])
    log_event(
        "INFO",
        "preview",
        "binding.completed",
        "WPS 当前宿主快照绑定完成",
        {
            "blocks": len(items),
            "request_id": request_id,
            "plan_id_short": plan.plan_id[:12],
            "confirmed": confirmed_count,
            "review": review_binding_count,
            "unresolved": unresolved_binding_count,
            "preview_eligible_count": preview_eligible_count,
            "duration_ms": int((time.monotonic() - started_at) * 1000),
        },
    )
    return {
        "plan_id": plan.plan_id,
        "binding_id": binding.binding_id,
        "document_mode": plan.document_mode,
        "document_mode_confidence": plan.document_mode_confidence,
        "block_count": len(items),
        "review_count": sum(
            1
            for item in items
            if item["review_level"] in {"review", "critical_review"}
        ),
        "unresolved_count": unresolved_binding_count,
        "confirmed_count": confirmed_count,
        "binding_review_count": review_binding_count,
        "preview_eligible_count": preview_eligible_count,
        "items": items,
    }
