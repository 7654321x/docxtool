"""Thin WPS adapter for the existing DocxTool document pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from docxtool.document.engine import export_doc
from docxtool.document.importer import DocxImporter
from docxtool.document.style_config import load_rules_and_settings
from docxtool.security import validate_docx_integrity

from .logging_adapter import document_log_context, log_event


@dataclass(frozen=True)
class FormatResult:
    output_path: Path
    log_path: Path
    document_mode: str
    paragraph_count: int
    heading_count: int
    body_count: int
    export_stats: Dict[str, Any]


def format_current_document(
    source_path: str,
    output_path: str,
    *,
    operation_id: str,
    log_dir: Path,
    format_config: Optional[dict] = None,
) -> FormatResult:
    """Format one saved DOCX through DocxTool's authoritative production chain."""
    source = Path(source_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()
    if source.suffix.lower() != ".docx" or not source.is_file():
        raise ValueError("INVALID_DOCX_INPUT")
    if target.suffix.lower() != ".docx":
        raise ValueError("INVALID_DOCX_OUTPUT")
    if source == target:
        raise ValueError("WPS_FORMAT_OUTPUT_MUST_BE_TEMPORARY")

    with document_log_context(source, log_dir, operation_id) as log_path:
        log_event(
            "INFO",
            "format",
            "pipeline.start",
            "开始调用 DocxTool 正式排版主链",
            {"operation_id": operation_id[:8], "recognition_mode": "authoritative"},
        )
        rules, settings, features = load_rules_and_settings(format_config)
        processing = features.setdefault("processing", {})
        if not isinstance(processing, dict):
            raise ValueError("INVALID_PROCESSING_OPTIONS")
        processing.setdefault("strategy", "structural")

        document = DocxImporter().load(
            str(source),
            rules,
            features=features,
            strict_preservation=True,
            recognition_mode="authoritative",
        )
        export_stats = export_doc(
            document,
            rules,
            settings,
            str(target),
            numbered_bold_enabled=bool(features.get("numbered_bold_enabled", True)),
            page_number_enabled=bool(features.get("page_number_enabled", True)),
            numbering_options=features.get("numbering"),
            page_number_options=features.get("page_number"),
            signature_block_options=features.get("signature_block"),
            table_format_options=features.get("table_format"),
            cleanup_options=features.get("cleanup"),
            letterhead_options=features.get("letterhead"),
        ) or {}
        validate_docx_integrity(str(target))

        headings = sum(1 for item in document.paragraphs if item.type_id.startswith("heading"))
        body = sum(1 for item in document.paragraphs if item.type_id == "body")
        log_event(
            "INFO",
            "format",
            "pipeline.completed",
            "DocxTool 正式排版主链执行完成",
            {
                "operation_id": operation_id[:8],
                "document_mode": document.doc_mode or "UNKNOWN",
                "paragraphs": len(document.paragraphs),
                "headings": headings,
                "body": body,
            },
        )
        return FormatResult(
            output_path=target,
            log_path=Path(log_path),
            document_mode=document.doc_mode or "UNKNOWN",
            paragraph_count=len(document.paragraphs),
            heading_count=headings,
            body_count=body,
            export_stats=dict(export_stats),
        )
