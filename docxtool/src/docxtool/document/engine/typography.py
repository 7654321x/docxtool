"""渲染阶段字体、数字和上标后处理。

本模块只处理输出段落的 run 字体、数字/拉丁字母字体拆分和上标格式。
它不识别段落类型，也不改变段落顺序。
"""

from __future__ import annotations

import copy
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt


DIGIT_LATIN_RE = re.compile(r"([0-9]+|[a-zA-Z]+)")


def set_run_fonts(run, cn_font="宋体", en_font="Times New Roman") -> None:
    """设置 run 的中英文字体。

    传入 python-docx run、中文字体名和英文字体名；返回 None。函数会把
    eastAsia 设置为中文字体，ascii/hAnsi 设置为英文字体。
    """
    run.font.name = en_font
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), cn_font)
    rFonts.set(qn("w:ascii"), en_font)
    rFonts.set(qn("w:hAnsi"), en_font)


def apply_superscript_split(paragraph) -> None:
    """拆分段落中形如 [n] 或 〔n〕 的上标标记。

    传入 python-docx 段落；返回 None。匹配到 1-2 位数字引用时，
    拆出独立 run，统一为 [n] 并设置上标。
    """
    superscript_pattern = re.compile(r"(\[\d{1,2}\]|〔\d{1,2}〕)")
    to_remove = []

    for run in list(paragraph.runs):
        text = run.text
        parts = superscript_pattern.split(text)
        if len(parts) == 1:
            continue

        parent = run._element.getparent()
        insert_before = run._element

        for part in parts:
            if not part:
                continue
            new_run = paragraph.add_run(part)
            source_rpr = run._element.find(qn("w:rPr"))
            if source_rpr is not None:
                destination_rpr = new_run._element.find(qn("w:rPr"))
                if destination_rpr is not None:
                    new_run._element.remove(destination_rpr)
                new_run._element.insert(0, copy.deepcopy(source_rpr))
            if superscript_pattern.match(part):
                number = re.search(r"\d+", part).group()
                new_run.text = f"[{number}]"
                new_run.font.superscript = True
                new_run.font.name = "Times New Roman"
                new_run.font.size = Pt(16)
            else:
                new_run.font.name = run.font.name
                new_run.font.size = run.font.size
                new_run.font.bold = run.font.bold
            parent.insert(parent.index(insert_before), new_run._element)
            if superscript_pattern.match(part):
                prev_elem = new_run._element.getprevious()
                if prev_elem is not None:
                    prev_rPr = prev_elem.find(qn("w:rPr"))
                    if prev_rPr is None:
                        prev_rPr = OxmlElement("w:rPr")
                        prev_elem.insert(0, prev_rPr)
                    keep = OxmlElement("w:keepNext")
                    prev_rPr.append(keep)

        to_remove.append(run._element)

    for elem in to_remove:
        elem.getparent().remove(elem)


def apply_digit_latin_font(paragraph) -> None:
    """把段落中的数字和拉丁字母拆分为 Times New Roman。

    传入 python-docx 段落；返回 None。含软换行的段落会跳过，避免破坏
    标题或手动换行结构。
    """
    for run in paragraph.runs:
        if run._element.find(qn("w:br")) is not None:
            return

    all_runs = list(paragraph.runs)
    for run in all_runs:
        text = run.text
        if not text or not DIGIT_LATIN_RE.search(text):
            continue
        if run.font.superscript:
            continue

        rPr_xml = run._element.find(qn("w:rPr"))
        rPr_clone = copy.deepcopy(rPr_xml) if rPr_xml is not None else None

        parts = DIGIT_LATIN_RE.split(text)
        insert_after = run._element
        for part in parts:
            if not part:
                continue
            new_r = OxmlElement("w:r")
            if rPr_clone is not None:
                new_r.append(copy.deepcopy(rPr_clone))
            text_node = OxmlElement("w:t")
            text_node.set(qn("xml:space"), "preserve")
            text_node.text = part
            new_r.append(text_node)
            if DIGIT_LATIN_RE.fullmatch(part):
                nrPr = new_r.find(qn("w:rPr"))
                if nrPr is None:
                    nrPr = OxmlElement("w:rPr")
                    new_r.insert(0, nrPr)
                fonts = nrPr.find(qn("w:rFonts"))
                if fonts is None:
                    fonts = OxmlElement("w:rFonts")
                    nrPr.append(fonts)
                fonts.set(qn("w:ascii"), "Times New Roman")
                fonts.set(qn("w:hAnsi"), "Times New Roman")
            insert_after.addnext(new_r)
            insert_after = new_r

        run._element.getparent().remove(run._element)


def apply_universal_superscript(paragraph) -> None:
    """统一已有上标 run 的显示格式。

    传入 python-docx 段落；返回 None。已有上标 run 会设置为三号
    Times New Roman，纯数字上标会补成 [n] 形式。
    """
    for run in paragraph.runs:
        if run.font.superscript:
            run.font.name = "Times New Roman"
            run.font.size = Pt(16)
            text = run.text.strip()
            if re.match(r"^\d+$", text):
                run.text = f"[{text}]"
