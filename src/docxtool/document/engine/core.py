# ruff: noqa: E402, F401
"""engine — 排版引擎。

职责：纯排版执行器，不做段落识别业务。
  - 输入 DocumentData + StyleRules → 输出 .docx
  - apply_style 为纯执行器，不处理 meta 判断
  - 所有 meta 映射在 export_doc 主循环中完成
"""

from __future__ import annotations

import sys
import copy
import hashlib
from typing import List

from docxtool.document.style_config import (
    StyleRule, PageSettings, logger, ExportError,
)
from docxtool.document.models import DocumentData, ParagraphData
from docxtool.document.engine.normal import resolve as _resolve_rule
from docxtool.document.engine.cleanup import cleanup_styles
from docxtool.document.engine.header_footer import apply_header_footer
from docxtool.document.engine.heading_body_split import (
    apply_heading1_report_split as _apply_heading1_report_split,
    verify_inline_heading_body_pair as _verify_inline_heading_body_pair,
)
from docxtool.document.engine.inline_effects import (
    INLINE_HEADING_BODY_MIN_CHARS as _INLINE_HEADING_BODY_MIN_CHARS,
    apply_colon_bold as _apply_colon_bold,
    apply_glossary_item as _apply_glossary_item,
    apply_inline_lead_bold as _apply_inline_lead_bold,
    apply_numbered_heading2_colon_format as _apply_numbered_heading2_colon_format,
    apply_numbered_heading2_period_format as _apply_numbered_heading2_period_format,
    apply_key_value_line_format as _apply_key_value_line_format,
    apply_report_first_sentence as _apply_report_first_sentence,
    apply_responsibility_line as _apply_responsibility_line,
    apply_special_bold as _apply_special_bold,
    enforce_inline_heading2_format as _enforce_inline_heading2_format,
    handle_heading_period as _handle_heading_period,
)
from docxtool.document.engine.numbering import normalize_numbering_text
from docxtool.document.engine.page_number import apply_page_number
from docxtool.document.engine.paragraph_format import (
    apply_first_line_indent_chars as _apply_first_line_indent_chars,
    apply_hanging_indent_chars as _apply_hanging_indent_chars,
    apply_left_indent_chars as _apply_left_indent_chars,
    apply_right_indent as _apply_right_indent,
    apply_rule_paragraph_format as _apply_rule_paragraph_format,
    apply_style,
    apply_style_safe,
    set_para_spacing as _set_para_spacing,
    set_widow_control as _set_widow_control,
)
from docxtool.document.engine.paragraph_styles import (
    enforce_body_paragraph_invariants as _enforce_body_paragraph_invariants,
    is_standalone_keep_heading as _is_standalone_keep_heading,
    set_keep_with_next as _set_keep_with_next,
    set_paragraph_style_id as _set_paragraph_style_id,
    style_id_for_type as _style_id_for_type,
)
from docxtool.document.engine.render_numbering import NumberingCounter, apply_numbering
from docxtool.document.engine.render_options import (
    feature_enabled as _feature_enabled,
    feature_options as _feature_options,
)
from docxtool.document.engine.render_text import (
    attachment_item_wrap_start_chars as _attachment_item_wrap_start_chars,
    attachment_note_wrap_start_chars as _attachment_note_wrap_start_chars,
    strip_heading_numbering as _strip_heading_numbering,
)
from docxtool.document.engine.render_types import (
    TYPE_TO_RULE_INDEX,
    is_body_flow_type,
    is_head_gap_follow_type,
    is_head_type_requiring_gap,
    is_structure_sensitive_type,
)
from docxtool.document.engine.inline import (
    segment_writer as _base_segment_writer,
    without_redundant_trailing_body_page_breaks as _without_redundant_trailing_body_page_breaks,
    write_inline_tokens as _write_inline_tokens,
)
from docxtool.document.engine.preservation import (
    NativeNumberingCopier as _NativeNumberingCopier,
    ReferencedStyleCopier as _ReferencedStyleCopier,
    SectionRelationshipCopier as _SectionRelationshipCopier,
    copy_image as _copy_image,
    copy_preserved_paragraph as _copy_preserved_paragraph,
    copy_table as _copy_table,
    set_object_caption_zero_spacing as _set_object_caption_zero_spacing,
)
from docxtool.document.engine.sections import (
    apply_page_settings,
    copy_paragraph_sectPr as _copy_paragraph_sectPr,
    has_imported_header_footer_refs as _has_imported_header_footer_refs,
    line_spacing_twips as _line_spacing_twips,
    preserve_even_and_odd_headers_setting as _preserve_even_and_odd_headers_setting,
    replace_body_sectPr as _replace_body_sectPr,
    set_sectPr_page_layout as _set_sectPr_page_layout,
)
from docxtool.document.engine.signature_block import (
    apply_signature_block,
    normalize_signature_attachment_order as _normalize_signature_attachment_order,
    validate_signature_attachment_order as _validate_signature_attachment_order,
)
from docxtool.document.engine.style_catalog import ensure_document_styles
from docxtool.document.engine.letterhead import apply_letterhead, detect_letterhead, LetterheadDetection
from docxtool.document.engine.typography import (
    apply_digit_latin_font as _apply_digit_latin_font,
    apply_superscript_split,
    apply_universal_superscript as _apply_universal_superscript,
    set_run_fonts as _set_run_fonts,
)

# ── python-docx 模块级导入 ──
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph


# ── XML 安全写入（防重复节点）──
def _set_unique(pPr, tag, element):
    """替换 pPr 中已存在的同名标签，避免重复 append 导致 Word 行为不一致。"""
    old = pPr.find(tag)
    if old is not None:
        pPr.remove(old)
    pPr.append(element)


def _segment_writer(para):
    """创建兼容旧调用的行内片段写入器，传入段落并返回 write 函数。"""
    return _base_segment_writer(para, set_run_fonts=_set_run_fonts)


def _is_terminal_body_paragraph(render_items, index: int, paragraph_data) -> bool:
    """Protect the final prose paragraph from a one-line trailing page."""
    if paragraph_data.type_id != 'body':
        return False
    return not any(
        getattr(item, 'type_id', '').strip() and not getattr(item, 'type_id', '').startswith('__')
        for item in render_items[index + 1:]
    )

# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

from docxtool.document.engine.export_pipeline import export_doc as _export_pipeline

def export_doc(doc_data: DocumentData, rules: List[StyleRule],
               settings: PageSettings, output_path: str,
               numbered_bold_enabled: bool = True,
               page_number_enabled: bool = True,
               numbering_options: dict | None = None,
               page_number_options: dict | None = None,
               signature_block_options: dict | None = None,
               table_format_options: dict | None = None,
               cleanup_options: dict | None = None,
               letterhead_options: dict | None = None) -> dict:
    """保留公开签名并把旧 core monkeypatch 命名空间注入真实导出主链。"""
    return _export_pipeline(
        doc_data,
        rules,
        settings,
        output_path,
        numbered_bold_enabled,
        page_number_enabled,
        numbering_options,
        page_number_options,
        signature_block_options,
        table_format_options,
        cleanup_options,
        letterhead_options,
        _compatibility_module=sys.modules[__name__],
    )
