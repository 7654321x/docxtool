"""Thin whole-document export orchestration."""

from __future__ import annotations

import hashlib

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
    logger.info("[引擎] 排版开始 source_sha256=%s", source_id)
    logger.info(f"[引擎] 共 {len(doc_data.paragraphs)} 段, {len(doc_data.tables)} 表格")

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
    return finalize_export(
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
