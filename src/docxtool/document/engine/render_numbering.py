"""Renderer-side heading numbering insertion.

本模块只负责渲染阶段把已经确定的标题层级编号写入输出段落。文本编号
识别、编号规范化和标题层级裁决仍由 importing / recognition /
normalization 侧负责，避免 Renderer 反向参与识别定型。
"""

from __future__ import annotations

from docx.shared import Pt

from docxtool.document.engine.typography import set_run_fonts
from docxtool.document.configuration.models import StyleRule, arabic_number, chinese_number
from docxtool.document.diagnostics.logging import logger


class NumberingCounter:
    """四级标题计数器；传入最终 type_id 递增状态，无返回值。"""

    a: int = 0
    b: int = 0
    c: int = 0
    d: int = 0

    def advance(self, type_id: str) -> None:
        """根据最终段落类型递增计数；传入 type_id，返回 None。"""
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
        """把编号模板渲染为文本；传入模板和 type_id，返回编号字符串。"""
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


def apply_numbering(paragraph, rule: StyleRule, counter: NumberingCounter) -> None:
    """在输出段落前插入编号；传入 paragraph、样式规则和计数器，返回 None。"""
    type_id = f"heading{rule.row_index + 1}" if rule.row_index < 4 else "body"
    numbering = counter.render(rule.numbering_pattern, type_id)
    if numbering:
        logger.debug(
            '[编号] %s → "%s" (a=%s b=%s c=%s d=%s)',
            rule.level_name,
            numbering,
            counter.a,
            counter.b,
            counter.c,
            counter.d,
        )
    if not numbering:
        return
    existing = paragraph.text.strip()
    if existing.startswith(numbering):
        return

    if paragraph.runs:
        first_run = paragraph.runs[0]
        new_run = paragraph.add_run(numbering)
        _format_numbering_run(new_run, rule)
        first_run._element.addprevious(new_run._element)
    else:
        new_run = paragraph.add_run(numbering)
        _format_numbering_run(new_run, rule)


def _format_numbering_run(run, rule: StyleRule) -> None:
    """设置编号 run 的字体；传入 run 和样式规则，直接修改 run 并返回 None。"""
    set_run_fonts(run, cn_font=rule.font, en_font="Times New Roman")
    run.font.size = Pt(rule.font_size_pt)
    if rule.bold is not None:
        run.font.bold = rule.bold
