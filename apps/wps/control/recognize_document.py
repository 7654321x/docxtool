"""Read-only recognition adapter for WPS preview and task-pane display."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from docxtool.sdk import recognize_docx

from .logging_adapter import document_log_context, file_identity, log_event


def recognize_document(
    source_path: str,
    *,
    log_dir: Path,
    format_config: Optional[dict] = None,
) -> Dict[str, Any]:
    """Run authoritative recognition and return text-free verified host locators."""
    source = Path(source_path).expanduser().resolve()
    if source.suffix.lower() != ".docx" or not source.is_file():
        raise ValueError("INVALID_DOCX_INPUT")
    operation_id = uuid.uuid4().hex
    with document_log_context(source, log_dir, operation_id) as log_path:
        log_event(
            "INFO",
            "preview",
            "recognition.start",
            "开始 WPS 预览识别",
            {"operation_id": operation_id[:8], "file_id": file_identity(source)},
        )
        plan = recognize_docx(
            source,
            processing_mode="structural",
            recognition_mode="authoritative",
            format_config=format_config,
            include_text=False,
            include_raw_text=False,
        )
        items: List[Dict[str, Any]] = []
        for block in plan.blocks:
            items.append(
                {
                    "block_id": block.block_id,
                    "block_index": block.block_index,
                    "physical_paragraph_index": block.physical_paragraph_index,
                    "physical_text_sha256": block.physical_text_sha256,
                    "raw_start_utf16": block.raw_start_utf16,
                    "raw_end_utf16": block.raw_end_utf16,
                    "text_sha256": block.text_sha256,
                    "type_id": block.type_id,
                    "format_role": block.format_role,
                    "review_level": block.review_level,
                    "confidence": block.classification_confidence,
                    "locator_verified": block.locator_verified,
                    "segment_index": block.segment_index,
                    "segment_count": block.segment_count,
                }
            )
        review_count = sum(1 for item in items if item["review_level"] in {"review", "critical_review"})
        unresolved_count = sum(1 for item in items if not item["locator_verified"])
        result = {
            "operation_id": operation_id,
            "plan_id": plan.plan_id,
            "document_mode": plan.document_mode,
            "document_mode_confidence": plan.document_mode_confidence,
            "block_count": len(items),
            "review_count": review_count,
            "unresolved_count": unresolved_count,
            "items": items,
            "log_file": Path(log_path).name,
        }
        log_event(
            "INFO",
            "preview",
            "recognition.completed",
            "WPS 预览识别完成",
            {
                "operation_id": operation_id[:8],
                "blocks": len(items),
                "review": review_count,
                "unresolved": unresolved_count,
            },
        )
        return result
