"""DOCX 段落行内 token 提取。"""

from __future__ import annotations

from typing import Callable, List

from docxtool.document.models import InlineToken


def extract_inline_tokens(paragraph) -> List[InlineToken]:
    """传入 python-docx 段落对象，返回文本、制表符、软换行和分页符 token 列表。"""
    from docx.oxml.ns import qn as _qn

    tokens: List[InlineToken] = []
    for run in paragraph._element.findall(".//" + _qn("w:r")):
        for child in run.iterchildren():
            if child.tag == _qn("w:t"):
                tokens.append(InlineToken("text", child.text or ""))
            elif child.tag == _qn("w:tab"):
                tokens.append(InlineToken("tab"))
            elif child.tag == _qn("w:br"):
                break_type = child.get(_qn("w:type"))
                tokens.append(InlineToken("page_break" if break_type == "page" else "line_break"))
            elif child.tag == _qn("w:cr"):
                tokens.append(InlineToken("line_break"))
            elif child.tag == _qn("w:lastRenderedPageBreak"):
                continue
    return tokens


def inline_tokens_text(tokens: List[InlineToken]) -> str:
    """传入行内 token 列表，返回用于识别的可见文本和软换行拼接结果。"""
    parts = []
    for token in tokens or []:
        if token.kind == "text":
            parts.append(token.text)
        elif token.kind == "tab":
            parts.append("\t")
        elif token.kind == "line_break":
            parts.append("\n")
    return "".join(parts)


def normalize_inline_tokens(
    tokens: List[InlineToken],
    *,
    normalize_text: Callable[[str], str],
    enabled: bool,
) -> List[InlineToken]:
    """传入 token 列表、文本归一化函数和开关，返回归一化后的 token 列表。"""
    if not enabled:
        return list(tokens or [])
    normalized = []
    for token in tokens or []:
        if token.kind == "text":
            normalized.append(InlineToken("text", normalize_text(token.text)))
        else:
            normalized.append(token)
    return normalized
