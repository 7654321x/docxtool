"""Small text helpers used by the DOCX renderer.

本模块只包含渲染阶段的纯文本辅助：附件说明回行列计算和标题旧编号
清理。它不判断段落类型，也不执行编号规范化。
"""

from __future__ import annotations

import re


_LEADING_NUM_RE = re.compile(
    r"^\s*(?:"
    r"[一二三四五六七八九十百千零〇]+[、\.．]+"
    r"|[（(][一二三四五六七八九十百千零〇0-9]+[）)]"
    r"|\d+[、\.．]+"
    r")\s*"
)


def attachment_note_wrap_start_chars(text: str) -> int:
    """计算附件说明首项回行列；传入文本，返回字符列数。"""
    match = re.match(r"^\s*附件\s*[:：]\s*(\d+)[.．、]\s*", text or "")
    if not match:
        return 5
    return 2 + 3 + len(match.group(1)) + 2


def attachment_item_wrap_start_chars(text: str) -> int:
    """计算附件续项回行列；传入文本，返回字符列数。"""
    match = re.match(r"^\s*(\d+)[.．、]\s*", text or "")
    if not match:
        return 8
    return 5 + len(match.group(1)) + 2


def strip_heading_numbering(text: str) -> str:
    """删除标题段首旧编号；传入文本，返回去除编号后的文本。"""
    return _LEADING_NUM_RE.sub("", text, count=1).lstrip()
