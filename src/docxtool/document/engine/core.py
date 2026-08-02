"""engine — 排版引擎。

职责：纯排版执行器，不做段落识别业务。
  - 输入 DocumentData + StyleRules → 输出 .docx
  - apply_style 为纯执行器，不处理 meta 判断
  - 所有 meta 映射在 export_doc 主循环中完成
"""

from __future__ import annotations

import copy
import hashlib
from typing import List

from docxtool.document.style_config import (
    StyleRule, PageSettings, logger, ExportError,
)
from docxtool.document.importer import DocumentData, ParagraphData
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
)
from docxtool.document.engine.inline import (
    segment_writer as _base_segment_writer,
    without_redundant_trailing_body_page_breaks as _without_redundant_trailing_body_page_breaks,
    write_inline_tokens as _write_inline_tokens,
)
from docxtool.document.engine.preservation import (
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
    """排版引擎主入口。DocumentData → .docx 文件。

    Returns:
        dict: 排版统计信息。
    """

    source_id = hashlib.sha256(str(doc_data.filepath).encode("utf-8")).hexdigest()[:12]
    logger.info("[引擎] 排版开始 source_sha256=%s", source_id)
    logger.info(f"[引擎] 共 {len(doc_data.paragraphs)} 段, {len(doc_data.tables)} 表格")

    doc = Document()
    ensure_document_styles(doc, rules, settings)
    section_relationship_parts = getattr(doc_data, "section_relationship_parts", {}) or {}
    removed_external_relationships: list[dict] = []
    relationship_part_copier = _SectionRelationshipCopier(
        doc.part.package,
        removed_external_relationships,
    )
    referenced_style_copier = _ReferencedStyleCopier(doc.styles.element)
    section_part_copier = relationship_part_copier if section_relationship_parts else None

    stats = {
        "total": len(doc_data.paragraphs),
        "heading1": 0, "heading1_report": 0, "heading2": 0, "heading3": 0, "heading4": 0,
        "body": 0, "fallback_count": 0, "style_fallback_count": 0, "numpr_removed": 0,
        "output_path": output_path,
        "removed_external_relationships": removed_external_relationships,
        "inline_heading_body_verified": 0,
    }

    # 查找页码规则（row 7）
    page_rule = rules[8] if len(rules) > 8 else StyleRule.default_for_row(8)

    prev_was_title = False
    prev_type_id = ""
    body_flow_started = False
    line_twips = _line_spacing_twips(settings)
    numbering_enabled = _feature_enabled(numbering_options, False)
    numbering_mode = str(_feature_options(numbering_options).get("mode", "safe") or "safe").lower()
    strict_preservation = bool(getattr(doc_data, "strict_preservation", False))
    normalization_processing = getattr(doc_data, "processing_strategy", "") == "normalize"

    render_items = (
        list(doc_data.paragraphs)
        if strict_preservation
        else _normalize_signature_attachment_order(doc_data.paragraphs)
    )
    if not strict_preservation:
        _validate_signature_attachment_order(render_items)
    paragraph_i = 0
    _deferred_body_log = []  # heading1 拆出的 body 日志
    inline_heading_body_pairs = []
    section_paragraphs = []
    protected_paragraph_elements = set()
    letterhead_detection = getattr(doc_data, "letterhead_detection", None) or LetterheadDetection()
    letterhead_enabled = _feature_enabled(letterhead_options, False)
    preserve_input_letterhead = not letterhead_enabled

    for i, pd in enumerate(render_items):
        # 表格占位符 → 原位复制
        if pd.type_id == "__table__":
            try:
                _copy_table(
                    doc,
                    pd.meta.get("table"),
                    relationship_part_copier,
                    referenced_style_copier,
                )
            except Exception as e:
                raise ExportError(f"表格完整复制失败，已中止导出: {e}") from e
            continue
        # 图片占位符 → 原位复制
        if pd.type_id == "__image__":
            try:
                protected_paragraph_elements.add(
                    _copy_image(doc, pd.meta.get("image_xml"), relationship_part_copier)
                )
            except Exception as e:
                raise ExportError(f"图片完整复制失败，已中止导出: {e}") from e
            continue
        if pd.type_id == "__object_caption__":
            try:
                caption_element = _copy_preserved_paragraph(
                    doc, pd.meta.get("paragraph_xml"), relationship_part_copier
                )
                _set_object_caption_zero_spacing(caption_element)
                protected_paragraph_elements.add(caption_element)
            except Exception as e:
                raise ExportError(f"题注完整复制失败，已中止导出: {e}") from e
            continue
        if pd.type_id == "__letterhead__":
            if preserve_input_letterhead:
                try:
                    protected_paragraph_elements.add(
                        _copy_preserved_paragraph(
                            doc,
                            pd.meta.get("paragraph_xml"),
                            relationship_part_copier,
                            referenced_style_copier,
                        )
                    )
                except Exception as e:
                    raise ExportError(f"已有版头完整复制失败，已中止导出: {e}") from e
            continue

        para_no = paragraph_i
        paragraph_i += 1
        try:
            logger.debug("[引擎] 段落 %s: type=%s chars=%s", para_no, pd.type_id, len(pd.text))

            # 确定对应的 StyleRule 索引
            rule_index = TYPE_TO_RULE_INDEX.get(pd.type_id)
            if rule_index is None:
                logger.warning("[渲染] 未知段落类型 %r，显式使用正文规则", pd.type_id)
                rule_index = 5
            raw_rule = rules[rule_index] if rule_index < len(rules) else StyleRule.default_for_row(rule_index)

            # glossary_title 特殊处理（内联段落）
            if pd.type_id == "glossary_title":
                resolved = copy.copy(raw_rule)
                resolved.row_index = 0
                resolved.font = "方正小标宋简体"
                resolved.font_size_pt = 22
                resolved.bold = False
                resolved.alignment = "居中"
                resolved.first_line_indent = 0.0
                para = doc.add_paragraph(pd.text)
                run = para.runs[0] if para.runs else para.add_run(pd.text)
                apply_style(para, resolved)
                _set_run_fonts(run, cn_font=resolved.font)
                run.font.size = Pt(resolved.font_size_pt)
                run.font.bold = resolved.bold
                _set_para_spacing(para, before_lines=1, after_lines=1)
                pPr = para._element.get_or_add_pPr()
                page_break = OxmlElement('w:pageBreakBefore')
                pPr.append(page_break)
                prev_was_title = True
                continue

            # meta → 重写规则（按文种分派）
            resolved = _resolve_rule(pd, raw_rule, rules)

            # 空行插入（三号 16pt 行距 28 磅）
            # date_line 后的留白由段后间距控制，避免生成真实空段落。
            need_gap = (prev_was_title and is_head_gap_follow_type(pd.type_id)
                        and prev_type_id not in ("date_line", "role_name")
                        and pd.text.strip())

            if need_gap and not letterhead_enabled and not strict_preservation:
                spacer = doc.add_paragraph("")
                spPPr = spacer._element.get_or_add_pPr()
                spSpacing = OxmlElement('w:spacing')
                spSpacing.set(qn('w:line'), str(line_twips))
                spSpacing.set(qn('w:lineRule'), 'exact')
                spPPr.append(spSpacing)
                spacer.add_run("").font.size = Pt(16)

            # 标题先清理旧编号，再建段落
            text = pd.text
            # A standalone first-level title is not a body sentence.  Its
            # terminal Chinese full stop is copied formatting noise and is
            # removed in every editable processing mode.
            if (
                not strict_preservation
                and pd.type_id == "heading1"
                and text.rstrip().endswith("。")
            ):
                text = text.rstrip()[:-1]
            if numbering_enabled and normalization_processing:
                numbering_result = normalize_numbering_text(text, safe=numbering_mode != "off")
                if numbering_result.changed:
                    text = numbering_result.text
            numbering_correction = bool(pd.meta.get("numbering_correction"))
            if pd.type_id.startswith("heading") and (
                normalization_processing or numbering_correction
            ):
                text = _strip_heading_numbering(text)
                # 一/二级标题特殊处理：句号分割的行内标题（政协报告体例）
                if normalization_processing and pd.type_id in ("heading1", "heading2"):
                    text = _handle_heading_period(text)

            inline_tokens = list(getattr(pd, "inline_tokens", None) or [])
            if normalization_processing:
                inline_tokens = _without_redundant_trailing_body_page_breaks(
                    pd,
                    render_items[i + 1] if i + 1 < len(render_items) else None,
                    inline_tokens,
                )
            if inline_tokens and text == pd.text:
                para = doc.add_paragraph("")
                _write_inline_tokens(para, inline_tokens)
            else:
                para = doc.add_paragraph(text)
            _set_paragraph_style_id(para, _style_id_for_type(pd.type_id))
            next_pd = render_items[i + 1] if i + 1 < len(render_items) else None
            if _is_standalone_keep_heading(pd, next_pd, para.text):
                _set_keep_with_next(para)

            # 逐段写入 XML 属性
            pPr = para._element.get_or_add_pPr()
            spacing = OxmlElement('w:spacing')
            # 段前/段后间距（自然模式下生效）
            before_lines = settings.space_before_line + (
                1 if need_gap and letterhead_enabled else 0
            )
            if strict_preservation and need_gap and not letterhead_enabled:
                before_lines += 1
            before_twip = int(before_lines * line_twips)
            after_twip = int(settings.space_after_line * line_twips)
            spacing.set(qn('w:before'), str(before_twip))
            spacing.set(qn('w:after'), str(after_twip))
            spacing.set(qn('w:beforeLines'), str(int(before_lines * 100)))
            spacing.set(qn('w:afterLines'), str(int(settings.space_after_line * 100)))
            # 网格模式 → 固定行距；自然模式(每行=0) → 不设，让段间距生效
            if settings.chars_per_line > 0:
                spacing.set(qn('w:line'), str(line_twips))
                spacing.set(qn('w:lineRule'), 'exact')
            pPr.append(spacing)
            if i < 3:
                logger.info(f"[段落{i}] XML: grid={'on' if settings.chars_per_line>0 else 'off'}")
            # 禁用 Word 自动上下文间距
            ctxSpc = OxmlElement('w:contextualSpacing')
            ctxSpc.set(qn('w:val'), '0')
            _set_unique(pPr, qn('w:contextualSpacing'), ctxSpc)
            # 关闭孤行控制
            wc = OxmlElement('w:widowControl')
            wc.set(qn('w:val'), '0')
            _set_unique(pPr, qn('w:widowControl'), wc)

            # 应用样式（带降级）
            if not apply_style_safe(para, resolved):
                logger.warning(f"[引擎] 段落 {i} 样式降级，继续后续")
                first_start = getattr(resolved, 'first_line_indent', 2.0) or 2.0
                _apply_hanging_indent_chars(para, first_start, first_start)

            _apply_rule_paragraph_format(para, resolved, line_twips)

            if pd.type_id == "dispatch_number":
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _apply_first_line_indent_chars(para, 0)

            # GB/T 9704 落款位置：发文机关右空 2 字，成文日期右空 4 字。
            # 直接格式固定最终位置，避免浏览器旧配置覆盖规范值。
            if pd.type_id == "sign_org":
                _apply_right_indent(para, 2)
            elif pd.type_id == "sign_date":
                _apply_right_indent(para, 4)

            # 头部署名/日期的相邻间距：
            # 主标题与职务姓名之间空 1 行，职务姓名与后续标题/正文也空 1 行。
            if pd.type_id in ("role_name", "author_line"):
                head_gap = (
                    1
                    if pd.type_id == "role_name"
                    and prev_type_id in ("title", "title_cont")
                    else 0
                )
                _set_para_spacing(
                    para,
                    before_lines=head_gap,
                    after_lines=(
                        1
                        if pd.type_id == "role_name"
                        and (next_pd is None or next_pd.type_id != "date_line")
                        else 0
                    ),
                    line_twips=line_twips,
                )
            elif pd.type_id == "date_line":
                _set_para_spacing(para, before_lines=0, after_lines=1, line_twips=line_twips)
            elif pd.type_id == "addressing" and body_flow_started:
                # Opening salutations keep the configured one-line gap.  A
                # repeated salutation inside or after the speech body is part
                # of the body flow and must not create another blank line.
                _set_para_spacing(
                    para,
                    before_lines=0,
                    after_lines=0,
                    line_twips=line_twips,
                    explicit_zero=True,
                )
            elif pd.type_id in ("heading2", "heading3", "heading4"):
                _set_para_spacing(para, before_lines=0, after_lines=0, line_twips=line_twips)
            elif pd.type_id == "sign_org" and prev_type_id in (
                "attachment_note", "attachment_note_item"
            ):
                _set_para_spacing(para, before_lines=3, after_lines=0, line_twips=line_twips)

            # (colon_inline_body removed — scheme mode deleted)            # date_line 强制适应一行（自动计算压缩量）
            if getattr(resolved, 'date_line_compress', False):
                pPr = para._element.get_or_add_pPr()
                csc = OxmlElement('w:characterSpacingControl')
                csc.set(qn('w:val'), 'compressPunctuation')
                pPr.append(csc)
                # 自动计算字符间距压缩
                text_len = len(pd.text)
                if text_len > 27:
                    shrink = min(int((text_len - 27) * 5), 40)  # 每超出1字收紧0.25pt，最多2pt
                    for run in para.runs:
                        rPr = run._element.get_or_add_rPr()
                        sp = OxmlElement('w:spacing')
                        sp.set(qn('w:val'), str(-shrink))
                        rPr.append(sp)

            # glossary_title 独立分支保留；其他段前段后由 JSON StyleRule 控制。
            if pd.type_id == "glossary_title":
                _set_para_spacing(para, before_lines=1, after_lines=1, line_twips=line_twips)

            # Compatibility input can still contain a heading/body sentence
            # in one ParagraphData item. Split it once into a heading and one
            # complete body paragraph; later body sentences stay together.
            if not strict_preservation and pd.type_id == "heading1" and "。" in para.text:
                full_text = para.text
                expected_body_text = full_text.split("。", 1)[1].strip()
                body_rule = rules[5] if len(rules) > 5 else StyleRule.default_for_row(5)
                body_para = _apply_heading1_report_split(
                    para, full_text, resolved, body_rule, line_twips,
                    remove_heading_period=True,
                )
                if body_para is not None:
                    body_text = body_para.text
                    inline_heading_body_pairs.append((para, body_para, expected_body_text))
                    stats["body"] += 1
                    apply_superscript_split(body_para)
                    if numbered_bold_enabled:
                        _apply_special_bold(body_para, body_text)
                    _deferred_body_log.append(
                        f"[排版] #{i}h1→body | chars={len(body_text)} | "
                        f"字体={body_rule.font} | 字号={body_rule.font_size_pt}pt | 加粗={body_rule.bold} | "
                        f"对齐={body_rule.alignment} | 首行缩进={body_rule.first_line_indent}字符 | "
                        f"行距={settings.line_spacing_value}pt固定 | 对网=1"
                    )

            # heading2 句号分割，标题+正文同段（方案模式不拆分）
            if normalization_processing and pd.type_id == "heading2" and "。" in para.text:
                period_pos = para.text.find("。")
                full_text = para.text
                after = full_text[period_pos + 1:].strip()
                if len(after) >= _INLINE_HEADING_BODY_MIN_CHARS and para.runs:
                    para.runs[-1].text = full_text[:period_pos + 1]
                    body_run = para.add_run(full_text[period_pos + 1:])
                    body_rule = rules[5] if len(rules) > 5 else StyleRule.default_for_row(5)
                    _set_run_fonts(body_run, cn_font=body_rule.font, en_font="Times New Roman")
                    body_run.font.size = Pt(body_rule.font_size_pt)
                    body_run.font.bold = body_rule.bold
                    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

            # X是/固定词组 特殊加粗
            if pd.meta.get("numbered_bold") and para.runs:
                _apply_special_bold(para, pd.text)

            if pd.type_id == "responsibility_line" and para.runs:
                _apply_responsibility_line(para, pd.text)

            # 冒号关键词加粗（如"责任单位：区政府" → "责任单位："加粗）
            if pd.type_id != "responsibility_line" and pd.meta.get("colon_bold") and para.runs:
                _apply_colon_bold(para, pd.text)

            if (pd.type_id == "responsibility_line" or pd.meta.get("colon_bold")) and para.runs:
                _apply_key_value_line_format(para)

            # Legacy report metadata still reaches this compatibility branch
            # when the generic structural split did not already consume it.
            if (
                normalization_processing
                and pd.meta.get("heading1_report_split")
                and para.runs
                and "。" in para.text
            ):
                body_rule = rules[5] if len(rules) > 5 else StyleRule.default_for_row(5)
                expected_body_text = pd.text.split("。", 1)[1].strip()
                body_para = _apply_heading1_report_split(para, pd.text, resolved, body_rule, line_twips)
                if body_para is not None:
                    inline_heading_body_pairs.append((para, body_para, expected_body_text))
                    stats["body"] += 1

            # Source-backed inline emphasis keeps one physical body paragraph.
            if pd.meta.get("inline_lead_bold") and para.runs:
                _apply_inline_lead_bold(para, pd.text, resolved)
            # 报告首句加粗（首句楷体_GB2312 加粗，剩余仿宋正文）
            elif pd.meta.get("report_first_sentence_bold") and para.runs:
                _apply_report_first_sentence(para, pd.text, resolved)

            # 编号：从 meta 读取预计算编号，插入到第一个 run 前
            numbering = "" if strict_preservation or pd.meta.get("colon_inline_body") else pd.meta.get("numbering", "")
            logger.debug(f"[编号] meta={numbering!r} type={pd.type_id}")
            if numbering and para.runs:
                new_r = OxmlElement('w:r')
                t = OxmlElement('w:t')
                t.text = numbering
                new_r.append(t)
                # 设置字体
                rPr = OxmlElement('w:rPr')
                rF = OxmlElement('w:rFonts')
                rF.set(qn('w:eastAsia'), resolved.font)
                rF.set(qn('w:ascii'), 'Times New Roman')
                rF.set(qn('w:hAnsi'), 'Times New Roman')
                rPr.append(rF)
                sz = OxmlElement('w:sz')
                sz.set(qn('w:val'), str(int(resolved.font_size_pt * 2)))  # half-pt → 1/2pt
                rPr.append(sz)
                if resolved.bold:
                    b = OxmlElement('w:b')
                    rPr.append(b)
                new_r.insert(0, rPr)
                para.runs[0]._element.addprevious(new_r)

            if pd.type_id == "heading2":
                body_rule = rules[5] if len(rules) > 5 else StyleRule.default_for_row(5)
                _enforce_inline_heading2_format(para, resolved.bold, body_rule.bold)

            # 名词解释条目（编号后执行：关键词黑体，正文仿宋）
            if pd.meta.get("glossary_item") and para.runs:
                _apply_glossary_item(para, pd.text, resolved)

            # 上标拆分
            apply_superscript_split(para)

            # 最终强制 snapToGrid
            pPr_final = para._element.get_or_add_pPr()
            snap_val = '0' if pd.type_id in ('title', 'heading1', 'heading2', 'heading3', 'heading4') else '1'
            snap = OxmlElement('w:snapToGrid')
            snap.set(qn('w:val'), snap_val)
            _set_unique(pPr_final, qn('w:snapToGrid'), snap)
            if _is_terminal_body_paragraph(render_items, i, pd):
                _set_widow_control(para, True)
            if pd.meta.get("sectPr") is not None:
                section_paragraphs.append((para, pd.meta.get("sectPr")))
                _copy_paragraph_sectPr(
                    para,
                    pd.meta.get("sectPr"),
                    section_relationship_parts,
                    section_part_copier,
                    settings,
                    doc_data.doc_mode,
                )
            # 段落排版日志（每段汇总格式信息）
            text_digest = hashlib.sha256(pd.text.encode("utf-8")).hexdigest()[:12]
            indent = getattr(resolved, 'first_line_indent', 0)
            logger.info(
                f"[排版] #{i} {pd.type_id} | "
                f"chars={len(pd.text)} text_sha256={text_digest} | "
                f"字体={resolved.font} | "
                f"字号={resolved.font_size_pt}pt | "
                f"加粗={resolved.bold} | "
                f"对齐={resolved.alignment} | "
                f"首行缩进={int(indent)}字符 | "
                    f"行距={settings.line_spacing_value}pt固定 | "
                f"对网={snap_val}"
            )
            # 输出 heading1 拆出的 body 日志
            for log_line in _deferred_body_log:
                logger.info(log_line)
            _deferred_body_log.clear()

            # 记录头部区域；后接正文或一级标题时需要空一行。
            prev_was_title = is_head_type_requiring_gap(pd.type_id)
            prev_type_id = pd.type_id
            if is_body_flow_type(pd.type_id):
                body_flow_started = True

            # 统计
            if pd.type_id in stats:
                stats[pd.type_id] += 1
            elif pd.type_id.startswith("heading"):
                k = pd.type_id
                stats[k] = stats.get(k, 0) + 1
            else:
                stats["body"] += 1

        except Exception as e:
            logger.error(f"[引擎] 段落 {i} 异常: {e}，降级为纯文本")
            # 降级兜底：不跳过，用原始文本 + 正文格式写入
            try:
                fallback = doc.add_paragraph(pd.text)
                fallback.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                stats["body"] += 1
            except Exception:
                pass  # 最终兜底：实在写不了才跳过
            continue

    # 后处理：上标统一
    for para in doc.paragraphs:
        if para._p in protected_paragraph_elements:
            continue
        _apply_universal_superscript(para)

    # 后处理：数字/字母 → Times New Roman
    for para in doc.paragraphs:
        if para._p in protected_paragraph_elements:
            continue
        _apply_digit_latin_font(para)

    # 版头只负责首页正文流，不得覆盖整篇文档的页面设置。
    page_settings = settings
    apply_page_settings(doc, page_settings, doc_data.doc_mode)
    _preserve_even_and_odd_headers_setting(doc, doc_data)

    # Structural-preservation mode may split a previously fused leading
    # paragraph into a document number, title and role line.  The source-level
    # detector cannot see that virtual structure, so inspect the rebuilt body
    # once before deciding whether to preserve or complete an existing header.
    apply_detection = letterhead_detection
    if letterhead_detection.status == "none":
        rebuilt_detection = detect_letterhead(doc)
        if rebuilt_detection.status != "none":
            apply_detection = rebuilt_detection
    if letterhead_enabled and letterhead_detection.status != "none":
        # Existing source blocks were intentionally omitted above. Keep the
        # original status for reporting without applying source indexes to the
        # rebuilt output body.
        apply_detection = LetterheadDetection(
            letterhead_detection.status,
            (),
            letterhead_detection.details,
        )
    letterhead_result = apply_letterhead(
        doc,
        letterhead_options,
        detection=apply_detection,
        rules=rules,
        settings=page_settings,
    )
    # 版头在全局西文字体后处理之后生成，因此需要补做同一轮扫描。
    for element in letterhead_result.protected_elements:
        if element.tag == qn("w:p"):
            _apply_digit_latin_font(Paragraph(element, doc._body))
    protected_paragraph_elements.update(letterhead_result.protected_elements)
    stats["letterhead_detection"] = letterhead_result.detection
    stats["letterhead_action"] = letterhead_result.action
    stats["compatibility_warnings"] = list(letterhead_result.warnings)

    for para, sectPr in section_paragraphs:
        _copy_paragraph_sectPr(
            para,
            sectPr,
            section_relationship_parts,
            section_part_copier,
            page_settings,
            doc_data.doc_mode,
        )

    _replace_body_sectPr(
        doc,
        getattr(doc_data, "body_sectPr", None),
        section_relationship_parts,
        section_part_copier,
        page_settings,
        doc_data.doc_mode,
    )

    stats["signature_blocks_adjusted"] = apply_signature_block(
        doc, signature_block_options
    )

    if page_number_options is not None:
        if _feature_enabled(page_number_options, True):
            page_options = dict(_feature_options(page_number_options))
            page_options.setdefault("font_name", page_rule.font)
            page_options.setdefault("font_size_pt", page_rule.font_size_pt)
            page_options.setdefault("bold", page_rule.bold)
            if isinstance(page_options.get("first_page"), bool):
                page_options["first_page"] = "show" if page_options["first_page"] else "hide"
            apply_page_number(doc, page_options)
    elif page_number_enabled:
        apply_page_number(
            doc,
            {
                "style": "dash",
                "position": "outside",
                "first_page": True,
                "font_name": page_rule.font,
                "font_size_pt": page_rule.font_size_pt,
                "bold": page_rule.bold,
                "offset_from_text_mm": 7,
            },
        )

    if _feature_enabled(table_format_options, False):
        logger.info("[表格] 当前阶段仅原样复制，已忽略表格格式化配置")
    if _feature_enabled(cleanup_options, False):
        cleanup_styles(doc, _feature_options(cleanup_options), protected_paragraph_elements)

    # 页面行数诊断
    page_h_cm = (
        page_settings.page_height_cm
        - page_settings.margin_top_cm
        - page_settings.margin_bottom_cm
    )
    max_lines = page_h_cm / (page_settings.line_spacing_value * 0.0353)  # pt→cm
    logger.info(f"[页面] 版心高度={page_h_cm:.1f}cm 行距={page_settings.line_spacing_value}pt → 理论最大={max_lines:.1f}行 设定={page_settings.lines_per_page}行")

    invariant_stats = _enforce_body_paragraph_invariants(doc, protected_paragraph_elements)
    stats.update(invariant_stats)
    for heading_para, body_para, expected_body_text in inline_heading_body_pairs:
        _verify_inline_heading_body_pair(heading_para, body_para, expected_body_text)
    stats["inline_heading_body_verified"] = len(inline_heading_body_pairs)
    stats["style_fallback_count"] = stats["fallback_count"]
    if invariant_stats["fallback_count"] or invariant_stats["numpr_removed"]:
        logger.info(
            "[结构样式] fallback_count=%s numpr_removed=%s",
            invariant_stats["fallback_count"],
            invariant_stats["numpr_removed"],
        )

    # 保存
    try:
        doc.save(output_path)
        logger.info("[引擎] 排版完成 output_sha256=%s", hashlib.sha256(str(output_path).encode("utf-8")).hexdigest()[:12])
    except Exception as e:
        raise ExportError(f"保存失败 {output_path}: {e}")

    return stats
