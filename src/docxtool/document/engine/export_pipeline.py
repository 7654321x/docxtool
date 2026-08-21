"""Thin whole-document export orchestration."""

from __future__ import annotations

import hashlib
import time

from docxtool.document.diagnostics import log_event

from .export_finalize import finalize_export
from .paragraph_renderer import render_document_items
from .render_context import prepare_render_context


def export_doc(doc_data, rules, settings, output_path,
               numbered_bold_enabled=True,
               page_number_enabled=True,
               numbering_options=None,
               page_number_options=None,
               signature_block_options=None,
               table_format_options=None,
               cleanup_options=None,
               letterhead_options=None,
               *,
               style_profile="docxtool",
               _compatibility_module=None):
    """Prepare, render, finalize, and return the unchanged export statistics."""
    if _compatibility_module is None:
        from docxtool.document.engine import core as _compatibility_module

    logger = _compatibility_module.logger
    source_id = hashlib.sha256(str(doc_data.filepath).encode("utf-8")).hexdigest()[:12]
    render_started = time.monotonic()
    log_event(
        logger,
        20,
        "render.start",
        "开始渲染文档",
        module="engine",
        component="render",
        fields={
            "document_id": source_id,
            "paragraph_count": len(doc_data.paragraphs),
        },
    )
    try:
        context = prepare_render_context(
            doc_data,
            rules,
            settings,
            output_path,
            numbering_options,
            letterhead_options,
            style_profile,
            compatibility_module=_compatibility_module,
        )
        render_document_items(
            context,
            doc_data,
            rules,
            settings,
            numbered_bold_enabled,
            compatibility_module=_compatibility_module,
        )
    except Exception as exc:
        log_event(
            logger,
            40,
            "render.failed",
            "文档渲染失败",
            module="engine",
            component="render",
            fields={
                "document_id": source_id,
                "error_code": "DOCUMENT_RENDER_FAILED",
                "error_type": type(exc).__name__,
            },
            exc_info=True,
        )
        raise
    rendered_doc = getattr(context, "doc", None)
    section_count = len(getattr(rendered_doc, "sections", ()))
    log_event(
        logger,
        20,
        "render.complete",
        "文档渲染完成",
        module="engine",
        component="render",
        fields={
            "document_id": source_id,
            "paragraph_count": len(doc_data.paragraphs),
            "section_count": section_count,
            "duration_ms": int((time.monotonic() - render_started) * 1000),
        },
    )

    export_started = time.monotonic()
    log_event(
        logger,
        20,
        "export.start",
        "开始导出 DOCX",
        module="exporter",
        component="pipeline",
        fields={"document_id": source_id},
    )
    try:
        stats = finalize_export(
            context,
            doc_data,
            rules,
            settings,
            output_path,
            page_number_enabled,
            page_number_options,
            signature_block_options,
            table_format_options,
            cleanup_options,
            letterhead_options,
            compatibility_module=_compatibility_module,
        )
    except Exception as exc:
        log_event(
            logger,
            40,
            "export.failed",
            "DOCX 导出失败",
            module="exporter",
            component="pipeline",
            fields={
                "document_id": source_id,
                "error_code": "DOCUMENT_EXPORT_FAILED",
                "error_type": type(exc).__name__,
            },
            exc_info=True,
        )
        raise
    exported_doc = getattr(context, "doc", None)
    section_count = len(getattr(exported_doc, "sections", ()))
    log_event(
        logger,
        20,
        "export.complete",
        "DOCX 导出完成",
        module="exporter",
        component="pipeline",
        fields={
            "document_id": source_id,
            "section_count": section_count,
            "duration_ms": int((time.monotonic() - export_started) * 1000),
            "warning_count": len(stats.get("compatibility_warnings", []) or [])
            if isinstance(stats, dict)
            else 0,
        },
    )
    return stats
