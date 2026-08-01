"""engine — 排版引擎。

职责：纯排版执行器，不做段落识别业务。
  - 输入 DocumentData + StyleRules → 输出 .docx
  - apply_style 为纯执行器，不处理 meta 判断
  - 所有 meta 映射在 export_doc 主循环中完成
"""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Dict, List, Optional

from docxtool.document.style_config import (
    StyleRule, PageSettings, chinese_number,
    arabic_number, logger, ExportError,
)
from docxtool.document.importer import DocumentData, ParagraphData
from docxtool.document.engine.normal import resolve as _resolve_rule
from docxtool.document.engine.cleanup import cleanup_styles
from docxtool.document.engine.header_footer import apply_header_footer
from docxtool.document.engine.numbering import normalize_numbering_text
from docxtool.document.engine.page_number import apply_page_number
from docxtool.document.engine.inline import (
    copy_run_style as _copy_run_style,
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
from docxtool.document.engine.signature_block import apply_signature_block
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


# ── 落款排版辅助 ──
def _apply_right_indent(para, n=2):
    # Signature placement is a final direct format.  Do not leave inherited
    # distributed alignment or character-based left/first-line indents from a
    # copied body paragraph in the generated document.
    para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pPr = para._element.get_or_add_pPr()
    ind = pPr.find(qn('w:ind'))
    if ind is None:
        ind = OxmlElement('w:ind')
        pPr.append(ind)
    for attr in ('w:left', 'w:leftChars', 'w:firstLine', 'w:firstLineChars', 'w:hanging', 'w:hangingChars'):
        ind.attrib.pop(qn(attr), None)
    ind.set(qn('w:right'), str(int(n * 560)))
    ind.set(qn('w:rightChars'), str(int(round(n * 100))))


def _set_widow_control(para, enabled: bool) -> None:
    pPr = para._element.get_or_add_pPr()
    widow_control = OxmlElement('w:widowControl')
    widow_control.set(qn('w:val'), '1' if enabled else '0')
    _set_unique(pPr, qn('w:widowControl'), widow_control)


def _is_terminal_body_paragraph(render_items, index: int, paragraph_data) -> bool:
    """Protect the final prose paragraph from a one-line trailing page."""
    if paragraph_data.type_id != 'body':
        return False
    return not any(
        getattr(item, 'type_id', '').strip() and not getattr(item, 'type_id', '').startswith('__')
        for item in render_items[index + 1:]
    )

def _apply_first_line_indent_chars(para, chars: int):
    """只设置首行缩进，不设置悬挂缩进。"""
    pPr = para._element.get_or_add_pPr()
    ind = pPr.find(qn('w:ind'))
    if ind is None:
        ind = OxmlElement('w:ind')
        pPr.append(ind)
    for attr in (qn('w:firstLine'), qn('w:firstLineChars'),
                 qn('w:left'), qn('w:leftChars'),
                 qn('w:hanging'), qn('w:hangingChars')):
        if attr in ind.attrib:
            del ind.attrib[attr]
    ind.set(qn('w:firstLineChars'), str(chars * 100))
    ind.set(qn('w:firstLine'), str(chars * 320))


def _apply_left_indent_chars(para, chars: float):
    """只设置整段左缩进，不设置首行或悬挂缩进。"""
    pPr = para._element.get_or_add_pPr()
    ind = pPr.find(qn('w:ind'))
    if ind is None:
        ind = OxmlElement('w:ind')
        pPr.append(ind)
    for attr in (qn('w:firstLine'), qn('w:firstLineChars'),
                 qn('w:left'), qn('w:leftChars'),
                 qn('w:hanging'), qn('w:hangingChars')):
        if attr in ind.attrib:
            del ind.attrib[attr]
    ind.set(qn('w:leftChars'), str(int(chars * 100)))
    ind.set(qn('w:left'), str(int(chars * 320)))


def _apply_hanging_indent_chars(para, first_chars: float, follow_chars: float) -> None:
    """兼容旧分支的兜底缩进，避免落回未定义变量路径。"""
    base = max(float(first_chars or 0), 0.0)
    follow = max(float(follow_chars or base), base)
    pPr = para._element.get_or_add_pPr()
    ind = pPr.find(qn('w:ind'))
    if ind is None:
        ind = OxmlElement('w:ind')
        pPr.append(ind)
    for attr in (qn('w:firstLine'), qn('w:firstLineChars'),
                 qn('w:left'), qn('w:leftChars'),
                 qn('w:hanging'), qn('w:hangingChars')):
        if attr in ind.attrib:
            del ind.attrib[attr]
    ind.set(qn('w:firstLineChars'), str(int(base * 100)))
    ind.set(qn('w:firstLine'), str(int(base * 320)))
    if follow > base:
        hanging = int(max(0, round((follow - base) * 100)))
        if hanging:
            ind.set(qn('w:hangingChars'), str(hanging))

def _attachment_note_wrap_start_chars(text: str) -> int:
    """附件说明首行回行列。

    无编号：`附件：正文` → 回行对齐到正文首字（5 字列）
    有编号：`附件：1. 正文` → 回行对齐到编号后的正文首字
    """
    m = re.match(r'^\s*附件\s*[:：]\s*(\d+)[.．、]\s*', text or "")
    if not m:
        return 5
    return 2 + 3 + len(m.group(1)) + 2

def _attachment_item_wrap_start_chars(text: str) -> int:
    """附件续项回行列：对齐到编号后的正文首字。"""
    m = re.match(r'^\s*(\d+)[.．、]\s*', text or "")
    if not m:
        return 8
    return 5 + len(m.group(1)) + 2

# ── 清理旧编号 ──
_LEADING_NUM_RE = re.compile(
    r"^\s*(?:"
    r"[一二三四五六七八九十百千零〇]+[、\.．]+"
    r"|[（(][一二三四五六七八九十百千零〇0-9]+[）)]"
    # A copied list number can carry duplicate punctuation (for example
    # "3..标题").  Consume the whole punctuation run before inserting the
    # canonical heading number, rather than leaving a second dot behind.
    r"|\d+[、\.．]+"
    r")\s*"
)

def _strip_heading_numbering(text: str) -> str:
    """去掉段首已有的编号，避免再次插入时重复。"""
    return _LEADING_NUM_RE.sub("", text, count=1).lstrip()


def _apply_special_bold(para, text: str) -> None:
    """特殊加粗入口：按匹配拆 run，每句独立加粗。"""
    if not para.runs:
        return
    from docxtool.document.style_config import NB_SUFFIXES as _NBS, NB_FIXED as _NBF
    import re as _re
    _suffixes = "|".join(_NBS)
    _fixed = "|".join(map(_re.escape, _NBF))
    XSHI = rf'(?:[一二三四五六七八九十]+(?:{_suffixes})|{_fixed})'
    parts = _re.split(f'(?={XSHI})', text)
    write = _segment_writer(para)
    for pi, part in enumerate(parts):
        if not part:
            continue
        if pi == 0:
            write(part, bold=False)
        elif _NBF and any(part.startswith(f) for f in _NBF):
            colon = part.find('：')
            if colon < 0:
                colon = part.find(':')
            if colon >= 0:
                write(part[:colon + 1], bold=True)
                write(part[colon + 1:], bold=False)
            else:
                write(part, bold=True)
        else:
            m = _re.match(rf'([一二三四五六七八九十]+(?:{_suffixes}).*?。)(.*)', part)
            if m:
                write(m.group(1), bold=True)
                write(m.group(2), bold=False)
            else:
                write(part, bold=True)

def _apply_fixed_bold(para, part: str) -> None:
    """固定词组：加粗到冒号止（如'比如：xxx' → 加粗'比如：'）。"""
    colon = part.find('：')
    if colon < 0:
        colon = part.find(':')
    if colon >= 0:
        br = para.add_run(part[:colon+1])
        br.font.bold = True
        if part[colon+1:]:
            nr = para.add_run(part[colon+1:])
            nr.font.bold = False
    else:
        r = para.add_run(part)
        r.font.bold = True

def _apply_numbered_bold(para, part: str) -> None:
    """X是/X要：加粗到句号止（如'一是…。xxx' → 加粗'一是…。'）。"""
    from docxtool.document.style_config import NB_SUFFIXES
    import re as _re
    _suffixes = "|".join(NB_SUFFIXES)
    XSHI = rf'[一二三四五六七八九十]+(?:{_suffixes})'
    m = _re.match(f'({XSHI}.*?。)(.*)', part)
    if m:
        br = para.add_run(m.group(1))
        br.font.bold = True
        if m.group(2):
            nr = para.add_run(m.group(2))
            nr.font.bold = False
    else:
        r = para.add_run(part)
        r.font.bold = True

def _apply_colon_bold(para, text: str) -> None:
    """冒号关键词加粗：从行首到第一个冒号（含）加粗，后面正常。"""
    if not para.runs:
        return
    for colon in ('：', ':'):
        pos = text.find(colon)
        if pos > 0 and pos <= 10:
            write = _segment_writer(para)
            write(text[:pos + 1], bold=True)
            write(text[pos + 1:], bold=False)
            return


_RESPONSIBILITY_LABEL_RE = re.compile(r"责\s*任\s*单\s*位\s*[:：]")


def _normalize_responsibility_lines(text: str) -> list[str]:
    """Normalize responsibility labels and split repeated labels into separate lines."""
    normalized = _RESPONSIBILITY_LABEL_RE.sub("责任单位：", text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.strip().strip("“”\"'")
        if not line:
            continue
        parts = [part.strip() for part in re.split(r"(?=责任单位：)", line) if part.strip()]
        lines.extend(parts or [line])
    return lines


def _set_zero_first_line_indent(para) -> None:
    pPr = para._element.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.append(ind)
    ind.set(qn("w:firstLineChars"), "0")
    ind.set(qn("w:firstLine"), "0")
    for attr in ("w:hangingChars", "w:hanging"):
        q_attr = qn(attr)
        if q_attr in ind.attrib:
            del ind.attrib[q_attr]


def _force_responsibility_paragraph_format(para) -> None:
    para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _set_zero_first_line_indent(para)


def _apply_key_value_line_format(para) -> None:
    """Apply the fixed A:B key-value line layout without inheriting global spacing."""
    para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pPr = para._element.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.append(ind)

    has_manual_break = para._element.find(".//" + qn("w:br")) is not None
    if has_manual_break:
        ind.set(qn("w:leftChars"), "200")
        ind.set(qn("w:left"), "640")
        ind.set(qn("w:firstLineChars"), "0")
        ind.set(qn("w:firstLine"), "0")
    else:
        ind.set(qn("w:leftChars"), "0")
        ind.set(qn("w:left"), "0")
        ind.set(qn("w:firstLineChars"), "200")
        ind.set(qn("w:firstLine"), "640")
    for attr in ("w:hangingChars", "w:hanging"):
        ind.attrib.pop(qn(attr), None)

    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    spacing.set(qn("w:beforeLines"), "0")
    spacing.set(qn("w:afterLines"), "0")
    spacing.set(qn("w:line"), "560")
    spacing.set(qn("w:lineRule"), "exact")

    for run in para.runs:
        run.font.size = Pt(16)


def _apply_responsibility_line(para, text: str) -> None:
    """Render responsibility lines with one bold label per physical line."""
    if not para.runs:
        para.add_run("")

    lines = _normalize_responsibility_lines(text)
    if not lines:
        return

    base_run = para.runs[0]
    for run in para.runs:
        run.text = ""
    used_base = False

    def write(text_part: str, *, bold: bool | None = None):
        nonlocal used_base
        if not text_part:
            return None
        run = base_run if not used_base else para.add_run("")
        if used_base:
            _copy_run_style(base_run, run)
        used_base = True
        run.text = text_part
        if bold is not None:
            run.font.bold = bold
        return run

    def add_break() -> None:
        nonlocal used_base
        run = base_run if not used_base else para.add_run("")
        if used_base:
            _copy_run_style(base_run, run)
        used_base = True
        run.add_break()

    for index, line in enumerate(lines):
        if index:
            add_break()
        if line.startswith("责任单位："):
            write("责任单位：", bold=True)
            write(line[len("责任单位："):], bold=False)
        else:
            write(line, bold=False)

    _force_responsibility_paragraph_format(para)


def _insert_paragraph_after(para) -> Paragraph:
    new_p = OxmlElement("w:p")
    para._p.addnext(new_p)
    return Paragraph(new_p, para._parent)


def _apply_heading1_report_split(
    para,
    text: str,
    rule,
    body_rule,
    line_twips: int,
    *,
    remove_heading_period: bool = False,
):
    """Split a reliable heading1/body line into two differently styled paragraphs."""
    period = text.find('。')
    if period <= 0 or period >= len(text) - 1:
        return None
    body_text = text[period + 1:].strip()
    if len(body_text) < _INLINE_HEADING_BODY_MIN_CHARS:
        return None
    # A general independent heading1 drops its terminal full stop.  The legacy
    # heading1_report type deliberately preserves it for existing templates.
    heading_text = text[:period].rstrip() if remove_heading_period else text[:period + 1]
    # 截断当前段落为标题部分
    write = _segment_writer(para)
    write(heading_text)
    # 在当前段落后插入 body 段落
    body_para = _insert_paragraph_after(para)
    body_para.add_run(body_text)
    _set_paragraph_style_id(body_para, "DCT-Body")
    apply_style_safe(body_para, body_rule)
    _apply_rule_paragraph_format(body_para, body_rule, line_twips)
    bpPr = body_para._element.get_or_add_pPr()
    wc = OxmlElement('w:widowControl')
    wc.set(qn('w:val'), '0')
    _set_unique(bpPr, qn('w:widowControl'), wc)
    ctxSpc = OxmlElement('w:contextualSpacing')
    ctxSpc.set(qn('w:val'), '0')
    _set_unique(bpPr, qn('w:contextualSpacing'), ctxSpc)
    snap = OxmlElement('w:snapToGrid')
    snap.set(qn('w:val'), '1')
    _set_unique(bpPr, qn('w:snapToGrid'), snap)
    return body_para


def _verify_inline_heading_body_pair(heading_para, body_para, expected_body_text: str) -> None:
    """Reject an output where a protected heading/body split was altered.

    The importer guarantees that a numbered ``标题。正文`` source is split only
    once.  Keep a final renderer-side check because later style passes must
    never truncate the body or insert another paragraph between the pair.
    """
    if heading_para._p.getnext() is not body_para._p:
        raise ExportError("一级标题与其完整正文段不再相邻，已中止导出")
    if body_para.text != expected_body_text:
        raise ExportError("一级标题后的正文未完整保留，已中止导出")
    if body_para.style.style_id != "DCT-Body":
        raise ExportError("一级标题后的正文未使用正文样式，已中止导出")


def _apply_glossary_item(para, text: str, rule) -> None:
    """名词解释条目：编号不加粗 + 关键词（冒号前）黑体，正文（冒号后）仿宋。"""
    if len(para.runs) < 2:
        return
    cp = -1
    for c in ('：', ':'):
        cp = text.find(c)
        if cp > 0:
            break
    if cp <= 0:
        return
    kw = text[:cp + 1]   # 关键词（含冒号）
    bd = text[cp + 1:]   # 正文
    # 保留编号 run（runs[0]），清除内容 run（runs[-1]）
    para.runs[-1].text = ""
    # 关键词 → 黑体
    kr = para.add_run(kw)
    kr.font.name = "黑体"
    _set_run_fonts(kr, cn_font="黑体", en_font="Times New Roman")
    kr.font.size = Pt(rule.font_size_pt)
    kr.font.bold = False
    # 正文 → 仿宋
    if bd:
        br = para.add_run(bd)
        br.font.name = "仿宋_GB2312"
        _set_run_fonts(br, cn_font="仿宋_GB2312", en_font="Times New Roman")
        br.font.size = Pt(rule.font_size_pt)
        br.font.bold = False


def _apply_report_first_sentence(para, text: str, rule) -> None:
    """报告首句加粗：首句（到第一个 。）楷体加粗，剩余仿宋正文。"""
    if not para.runs:
        return
    period = text.find('。')
    if period <= 0:
        return
    # 首句（含句号）→ 楷体加粗
    first = text[:period + 1]
    rest = text[period + 1:]
    write = _segment_writer(para)
    write(first, bold=True, cn_font="楷体_GB2312", size_pt=rule.font_size_pt)
    # 剩余 → 仿宋
    if rest:
        write(rest, bold=False, cn_font=rule.font, size_pt=rule.font_size_pt)


def _apply_inline_lead_bold(para, text: str, rule) -> None:
    """Restore source-backed lead-sentence emphasis without splitting a body."""
    if not para.runs:
        return
    period = text.find("。")
    if period <= 0 or period >= len(text) - 1:
        return
    write = _segment_writer(para)
    write(
        text[:period + 1],
        bold=True,
        cn_font=rule.font,
        size_pt=rule.font_size_pt,
    )
    write(
        text[period + 1:],
        bold=rule.bold,
        cn_font=rule.font,
        size_pt=rule.font_size_pt,
    )


def _set_para_spacing(para, before_lines: float = 0, after_lines: float = 0,
                      line_twips: int = 560, *, explicit_zero: bool = False) -> None:
    """设置段前段后间距（单位：行）。"""
    pPr = para._element.get_or_add_pPr()
    spacing = OxmlElement('w:spacing')
    if before_lines > 0 or explicit_zero:
        spacing.set(qn('w:before'), str(int(round(before_lines * line_twips))))
        spacing.set(qn('w:beforeLines'), str(int(round(before_lines * 100))))
    if after_lines > 0 or explicit_zero:
        spacing.set(qn('w:after'), str(int(round(after_lines * line_twips))))
        spacing.set(qn('w:afterLines'), str(int(round(after_lines * 100))))
    if line_twips > 0:
        spacing.set(qn('w:line'), str(line_twips))
        spacing.set(qn('w:lineRule'), 'exact')
    _set_unique(pPr, qn('w:spacing'), spacing)


def _apply_rule_paragraph_format(para, rule: StyleRule, line_twips: int) -> None:
    """应用 JSON 中的段落级扩展配置。"""
    _set_para_spacing(
        para,
        before_lines=getattr(rule, "spacing_before", 0.0) or 0.0,
        after_lines=getattr(rule, "spacing_after", 0.0) or 0.0,
        line_twips=line_twips,
    )
    left_indent = getattr(rule, "left_indent", 0.0) or 0.0
    right_indent = getattr(rule, "right_indent", 0.0) or 0.0
    if left_indent > 0:
        _apply_left_indent_chars(para, left_indent)
    if right_indent > 0:
        _apply_right_indent(para, right_indent)
    if getattr(rule, "page_break_before", False):
        pPr = para._element.get_or_add_pPr()
        pb = OxmlElement('w:pageBreakBefore')
        _set_unique(pPr, qn('w:pageBreakBefore'), pb)


_INLINE_HEADING_BODY_MIN_CHARS = 5


def _enforce_inline_heading2_format(para, heading_bold: bool, body_bold: bool) -> None:
    """Apply configured boldness to an inline heading2 and its body text."""
    full_text = para.text
    period_pos = full_text.find("。")
    if period_pos < 0 or len(full_text[period_pos + 1:].strip()) < _INLINE_HEADING_BODY_MIN_CHARS:
        return
    inline_body_start = period_pos + 1

    cursor = 0
    for run in list(para.runs):
        text = run.text or ""
        if not text:
            continue
        start = cursor
        end = cursor + len(text)
        cursor = end

        if end <= inline_body_start:
            run.font.bold = heading_bold
            continue
        if start >= inline_body_start:
            run.font.bold = body_bold
            continue

        heading_text = text[:inline_body_start - start]
        body_text = text[inline_body_start - start:]
        run.text = heading_text
        run.font.bold = heading_bold
        body_run = para.add_run(body_text)
        _copy_run_style(run, body_run)
        body_run.font.bold = body_bold
        run._element.addnext(body_run._element)


def _handle_heading_period(text: str) -> str:
    """处理标题句号（heading2/heading3）。

    类型 A（独立）："（一）坚持党的领导。" → 去掉句号
    类型 B（行内）："1.深入学习…统一行动。我们举办…" → 保留整段
                      后续在 run 层拆分为标题 run + 正文 run（仿宋）
    """
    # 找第一个中文句号
    period_pos = text.find("。")
    if period_pos < 0:
        return text  # 无句号，类型 A，直接返回

    after_period = text[period_pos + 1:].strip()
    # 句号后达到最小正文长度 → 类型 B（行内标题），保留整段
    if len(after_period) >= _INLINE_HEADING_BODY_MIN_CHARS:
        return text
    # 句号后无内容或很短 → 类型 A（独立标题），去掉句号
    return text[:period_pos] + text[period_pos + 1:]


# ═══════════════════════════════════════════════════════════════
# 四级层级计数器（分级控制）
# ═══════════════════════════════════════════════════════════════

class NumberingCounter:
    """四级层级计数器：高级递增 → 低级清零。

    heading1 → a+=1, b=0, c=0, d=0
    heading2 → b+=1, c=0, d=0
    heading3 → c+=1, d=0
    heading4 → d+=1
    """
    a: int = 0
    b: int = 0
    c: int = 0
    d: int = 0

    def advance(self, type_id: str) -> None:
        if type_id == "heading1":
            self.a += 1
            self.b = 0
            self.c = 0
            self.d = 0
        elif type_id == "heading2":
            self.b += 1
            self.c = 0
            self.d = 0
        elif type_id == "heading3":
            self.c += 1
            self.d = 0
        elif type_id == "heading4":
            self.d += 1

    def render(self, pattern: str, type_id: str) -> str:
        """精确替换模板中的 {a}/{b}/{c}/{d}。只替换花括号变量，不动字面字母。"""
        if not pattern:
            return ""
        is_chinese = type_id in ("heading1", "heading2")
        num_fn = chinese_number if is_chinese else arabic_number
        result = pattern
        result = result.replace("{a}", num_fn(self.a))
        result = result.replace("{b}", num_fn(self.b))
        result = result.replace("{c}", arabic_number(self.c))
        result = result.replace("{d}", arabic_number(self.d))
        return result


# ═══════════════════════════════════════════════════════════════
# 纯样式执行器
# ═══════════════════════════════════════════════════════════════

def apply_style(paragraph, rule: StyleRule) -> None:
    """在 Run 级别设置字体。纯执行器，不处理 meta，不捕获异常。"""



    # 确保段落至少有一个 Run
    if not paragraph.runs:
        paragraph.add_run("")

    # 遍历所有 Run，中英分离字体
    for run in paragraph.runs:
        _set_run_fonts(run, cn_font=rule.font, en_font="Times New Roman")
        run.font.size = Pt(rule.font_size_pt)
        if rule.bold is not None:
            run.font.bold = rule.bold

    # 对齐
    align_id = _align_to_enum(rule.alignment, WD_ALIGN_PARAGRAPH)
    if align_id is not None:
        paragraph.alignment = align_id

    # 正文：启用网格对齐（row_index≥5 为正文/附件）
    if rule.row_index >= 5:
        pPr = paragraph._element.get_or_add_pPr()
        snap = OxmlElement('w:snapToGrid')
        snap.set(qn('w:val'), '1')
        _set_unique(pPr, qn('w:snapToGrid'), snap)

    # 标题：禁用网格对齐 + 孤行控制（row_index≤4 为标题）
    if rule.row_index < 5:
        pPr = paragraph._element.get_or_add_pPr()
        snap = OxmlElement('w:snapToGrid')
        snap.set(qn('w:val'), '0')
        _set_unique(pPr, qn('w:snapToGrid'), snap)
        widowControl = OxmlElement('w:widowControl')
        widowControl.set(qn('w:val'), '0')
        _set_unique(pPr, qn('w:widowControl'), widowControl)
        # 关闭字符间距（标题自然排列，不受网格拉宽）
        for run in paragraph.runs:
            rPr = run._element.get_or_add_rPr()
            sp = OxmlElement('w:spacing')
            sp.set(qn('w:val'), '0')
            rPr.append(sp)

    # 首行缩进：字符单位 w:firstLineChars（2字符 = 200）
    if rule.first_line_indent > 0:
        pPr = paragraph._element.get_or_add_pPr()
        ind = pPr.find(qn('w:ind'))
        if ind is None:
            ind = OxmlElement('w:ind')
            pPr.append(ind)
        ind.set(qn('w:firstLineChars'), str(int(rule.first_line_indent * 100)))
        # 清除 twip 单位避免冲突
        if qn('w:firstLine') in ind.attrib:
            del ind.attrib[qn('w:firstLine')]


def _align_to_enum(align_str: str, WD_ALIGN_PARAGRAPH) -> Optional[int]:
    """中文对齐字符串 → python-docx 对齐枚举。"""
    mapping = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "distribute": WD_ALIGN_PARAGRAPH.DISTRIBUTE,
    }
    # 传入的可能是中文，也有可能是英文
    zh_to_en = {
        "左对齐": "left", "居中": "center", "右对齐": "right",
        "两端对齐": "justify", "分散对齐": "distribute",
    }
    key = zh_to_en.get(align_str, align_str)
    return mapping.get(key)


def apply_style_safe(paragraph, rule: StyleRule) -> bool:
    """带降级的 apply_style 包装。"""
    try:
        apply_style(paragraph, rule)
        return True
    except Exception as e:
        logger.warning(f"[引擎] 字体 '{rule.font}' 应用失败: {e}，回退宋体")
        try:
            fallback = copy.copy(rule)
            fallback.font = "宋体"
            fallback.font_size_pt = 12
            fallback.bold = False
            apply_style(paragraph, fallback)
        except Exception as e2:
            logger.error(f"[引擎] 完全降级失败: {e2}")
        return False


# ═══════════════════════════════════════════════════════════════
# 编号
# ═══════════════════════════════════════════════════════════════

def apply_numbering(paragraph, rule: StyleRule, counter: NumberingCounter) -> None:
    """在段落前插入纯文本编号。"""
    numbering = counter.render(rule.numbering_pattern, f"heading{rule.row_index + 1}" if rule.row_index < 4 else "body")
    if numbering:
        logger.debug(f"[编号] {rule.level_name} → \"{numbering}\" (a={counter.a} b={counter.b} c={counter.c} d={counter.d})")
    if not numbering:
        return
    existing = paragraph.text.strip()
    if existing.startswith(numbering):
        return
    # XML 层：先创建 run，补齐字体，再移到最前
    if paragraph.runs:
        first_run = paragraph.runs[0]
        new_run = paragraph.add_run(numbering)
        _set_run_fonts(new_run, cn_font=rule.font, en_font="Times New Roman")
        new_run.font.size = Pt(rule.font_size_pt)
        if rule.bold is not None:
            new_run.font.bold = rule.bold
        first_run._element.addprevious(new_run._element)
    else:
        new_run = paragraph.add_run(numbering)
        _set_run_fonts(new_run, cn_font=rule.font, en_font="Times New Roman")
        new_run.font.size = Pt(rule.font_size_pt)
        if rule.bold is not None:
            new_run.font.bold = rule.bold


# ═══════════════════════════════════════════════════════════════
# Type → StyleRule 索引映射
# ═══════════════════════════════════════════════════════════════

TYPE_TO_RULE_INDEX: Dict[str, int] = {
    "title": 0, "title_cont": 0, "embedded_document_title": 0,
    "heading1": 1, "heading1_report": 1,  # 报告 heading1 同 row 1，但无编号
    "heading2": 2, "heading3": 3, "heading4": 4,
    "body": 5, "attachment": 5, "responsibility_line": 5,
    "dispatch_number": 5, "meeting_meta": 5,
    "addressing": 10, "date_line": 11, "author_line": 12, "role_name": 13,
    "title2": 14, "sign_off": 15,
    "glossary_title": 0, "glossary_item": 16,
    "attachment_note": 17, "attachment_note_item": 18,
    "attachment_page_mark": 19, "attachment_title": 20, "attachment_body": 21,
    "sign_org": 22, "sign_date": 23,
    "number": 6, "letter": 7,
    "page_number": 8, "superscript": 9,
}

TYPE_TO_STYLE_ID: Dict[str, str] = {
    "title": "DCT-Title",
    "title_cont": "DCT-Title",
    "embedded_document_title": "DCT-Title",
    "dispatch_number": "DCT-DocumentNumber",
    "meeting_meta": "DCT-Body",
    "date_line": "DCT-Date",
    "author_line": "DCT-Author",
    "role_name": "DCT-RoleName",
    "heading1": "DCT-Heading1",
    "heading1_report": "DCT-Heading1",
    "heading2": "DCT-Heading2",
    "heading3": "DCT-Heading3",
    "heading4": "DCT-Heading4",
    "body": "DCT-Body",
    "addressing": "DCT-Recipient",
    "responsibility_line": "DCT-Responsibility",
    "title2": "DCT-Heading2",
    "sign_org": "DCT-Signature",
    "sign_date": "DCT-Date",
    "attachment_note": "DCT-AttachmentNote",
    "attachment_note_item": "DCT-AttachmentNoteItem",
    "attachment_page_mark": "DCT-AttachmentMark",
    "attachment_title": "DCT-AttachmentTitle",
    "attachment_body": "DCT-AttachmentBody",
}

HEAD_TYPES_REQUIRING_GAP = ("title", "title_cont", "date_line", "author_line", "role_name")
HEAD_GAP_FOLLOW_TYPES = ("body", "attachment_body", "heading1")
BODY_FLOW_TYPES = frozenset({
    "body", "heading1", "heading1_report", "heading2", "heading3", "heading4",
    "title2", "responsibility_line", "attachment_note", "attachment_note_item",
    "attachment_page_mark", "attachment_title", "attachment_body", "sign_org", "sign_date",
})


def _feature_options(options: dict | None) -> dict:
    return options if isinstance(options, dict) else {}


def _feature_enabled(options: dict | None, default: bool = False) -> bool:
    opts = _feature_options(options)
    value = opts.get("enabled", default)
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on", "启用", "是"}:
        return True
    if raw in {"0", "false", "no", "off", "禁用", "否"}:
        return False
    return bool(default)


def _style_id_for_type(type_id: str) -> str:
    style_id = TYPE_TO_STYLE_ID.get(type_id)
    if style_id is None:
        logger.warning("[渲染] 未知段落类型 %r，显式使用正文样式", type_id)
        return "DCT-Body"
    return style_id


def _set_paragraph_style_id(paragraph, style_id: str) -> None:
    pPr = paragraph._element.get_or_add_pPr()
    old = pPr.find(qn("w:pStyle"))
    if old is not None:
        pPr.remove(old)
    p_style = OxmlElement("w:pStyle")
    p_style.set(qn("w:val"), style_id)
    pPr.insert(0, p_style)


def _set_keep_with_next(paragraph) -> None:
    pPr = paragraph._element.get_or_add_pPr()
    _set_unique(pPr, qn("w:keepNext"), OxmlElement("w:keepNext"))
    _set_unique(pPr, qn("w:keepLines"), OxmlElement("w:keepLines"))


def _paragraph_style_id(paragraph) -> str:
    pPr = paragraph._element.pPr
    if pPr is None:
        return ""
    p_style = pPr.find(qn("w:pStyle"))
    return p_style.get(qn("w:val")) if p_style is not None else ""


def _remove_paragraph_numbering(paragraph) -> bool:
    pPr = paragraph._element.pPr
    if pPr is None:
        return False
    num_pr = pPr.find(qn("w:numPr"))
    if num_pr is None:
        return False
    pPr.remove(num_pr)
    return True


def _enforce_body_paragraph_invariants(doc, protected_elements=None) -> dict[str, int]:
    """Ensure non-empty main-document paragraphs have DCT styles and no numPr."""
    fallback_count = 0
    numpr_removed = 0
    protected_elements = protected_elements or set()
    for paragraph in doc.paragraphs:
        if paragraph._p in protected_elements:
            continue
        if _remove_paragraph_numbering(paragraph):
            numpr_removed += 1
        if not paragraph.text.strip():
            continue
        style_id = _paragraph_style_id(paragraph)
        if style_id.startswith("DCT-"):
            continue
        _set_paragraph_style_id(paragraph, "DCT-Body")
        fallback_count += 1
    return {"fallback_count": fallback_count, "numpr_removed": numpr_removed}


def _is_standalone_keep_heading(
    pd: ParagraphData,
    next_pd: ParagraphData | None,
    rendered_text: str,
) -> bool:
    del next_pd, rendered_text
    return pd.type_id in {"attachment_page_mark", "attachment_title"}


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def _normalize_signature_attachment_order(paragraphs: list[ParagraphData]) -> list[ParagraphData]:
    """Enforce body → attachment note block → signature organization → date."""
    normalized = list(paragraphs)
    allowed = {"attachment_note", "attachment_note_item", "sign_org", "sign_date"}

    def ignorable_gap(item: ParagraphData) -> bool:
        return bool(
            not str(item.text or "").strip()
            and not item.type_id.startswith("__")
            and not (getattr(item, "inline_tokens", None) or [])
            and not (item.meta or {}).get("sectPr")
        )

    index = 0
    while index < len(normalized):
        if normalized[index].type_id not in allowed:
            index += 1
            continue
        end = index
        while end < len(normalized) and (
            normalized[end].type_id in allowed or ignorable_gap(normalized[end])
        ):
            end += 1
        block = [item for item in normalized[index:end] if item.type_id in allowed]
        notes = [item for item in block if item.type_id == "attachment_note"]
        note_items = [item for item in block if item.type_id == "attachment_note_item"]
        organizations = [item for item in block if item.type_id == "sign_org"]
        dates = [item for item in block if item.type_id == "sign_date"]
        if notes or (organizations and dates):
            normalized[index:end] = notes + note_items + organizations + dates
            end = index + len(notes) + len(note_items) + len(organizations) + len(dates)
        index = end
    return normalized


def _validate_signature_attachment_order(paragraphs: list[ParagraphData]) -> None:
    """Reject a non-strict render plan that separates a known signature pair."""
    visible = [item for item in paragraphs if str(item.text or "").strip()]
    for index, item in enumerate(visible):
        if item.type_id != "sign_date":
            continue
        prior_org_indexes = [
            position for position, candidate in enumerate(visible[:index])
            if candidate.type_id == "sign_org"
        ]
        if not prior_org_indexes:
            continue
        previous_org = prior_org_indexes[-1]
        if previous_org != index - 1:
            raise ExportError("落款单位与落款日期未保持连续，已中止导出")
        if any(
            candidate.type_id in {"attachment_note", "attachment_note_item"}
            for candidate in visible[previous_org + 1:index]
        ):
            raise ExportError("附件说明插入落款单位与日期之间，已中止导出")

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
            need_gap = (prev_was_title and pd.type_id in HEAD_GAP_FOLLOW_TYPES
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
            prev_was_title = (pd.type_id in HEAD_TYPES_REQUIRING_GAP)
            prev_type_id = pd.type_id
            if pd.type_id in BODY_FLOW_TYPES:
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


# ═══════════════════════════════════════════════════════════════
# 验证（依赖 python-docx）
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # NumberingCounter 验证
    nc = NumberingCounter()
    nc.advance("heading1")
    assert nc.a == 1 and nc.b == 0 and nc.c == 0 and nc.d == 0
    nc.advance("heading2")
    assert nc.a == 1 and nc.b == 1 and nc.c == 0 and nc.d == 0
    nc.advance("heading3")
    assert nc.a == 1 and nc.b == 1 and nc.c == 1 and nc.d == 0
    nc.advance("heading4")
    assert nc.a == 1 and nc.b == 1 and nc.c == 1 and nc.d == 1
    nc.advance("heading2")
    assert nc.b == 2 and nc.c == 0 and nc.d == 0, f"级联清零失败: {nc.b},{nc.c},{nc.d}"
    nc.advance("heading1")
    assert nc.a == 2 and nc.b == 0 and nc.c == 0 and nc.d == 0, f"heading1 级联清零失败: {nc}"

    # render 验证
    nc2 = NumberingCounter()
    nc2.a = 1
    nc2.b = 2
    nc2.c = 3
    nc2.d = 4
    assert nc2.render("{a}、", "heading1") == "一、", f"render 中文失败: {nc2.render('{a}、', 'heading1')}"
    assert nc2.render("（{b}）", "heading2") == "（二）", "render 括号中文失败"
    assert nc2.render("{c}.", "heading3") == "3.", "render 阿拉伯失败"
    assert nc2.render("({d})", "heading4") == "(4)", "render 括号阿拉伯失败"
    assert nc2.render("- 1 -", "page_number") == "- 1 -", "render 固定值不应变动"

    # TYPE_TO_RULE_INDEX
    assert TYPE_TO_RULE_INDEX["body"] == 5
    assert TYPE_TO_RULE_INDEX["title"] == 0
    assert TYPE_TO_RULE_INDEX["heading1"] == 1
    assert TYPE_TO_RULE_INDEX["heading2"] == 2
    assert TYPE_TO_RULE_INDEX["heading3"] == 3
    assert TYPE_TO_RULE_INDEX["heading4"] == 4

    # Regression: attachment continuation items should use whole-paragraph
    # left indent of 5 chars, with no hanging indent.
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET

    with TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "attachment_indent.docx"
        data = DocumentData(paragraphs=[
            ParagraphData("附件：1. 基本情况", "attachment_note", "附件：1. 基本情况", None),
            ParagraphData("2. 具体情况", "attachment_note_item", "2. 具体情况", None),
        ])
        export_doc(data, [StyleRule.default_for_row(i) for i in range(10)], PageSettings(), str(out))
        with ZipFile(out) as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = root.findall(".//w:body/w:p", ns)
        item_ind = paragraphs[1].find("w:pPr/w:ind", ns)
        assert item_ind is not None
        assert item_ind.get(qn("w:leftChars")) == "500", item_ind.attrib
        assert qn("w:hangingChars") not in item_ind.attrib and qn("w:hanging") not in item_ind.attrib

    print("✅ engine.py 纯函数验证全部通过")
