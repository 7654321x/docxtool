"""旧 importer 兼容链路使用的文种和报告标题证据。"""

from __future__ import annotations

import re

REPORT_HEADING_STARTS = ("一年来", "五年来")
_TITLE_KEYWORD_RE = re.compile(
    r"对照检查|述职报告|工作总结|工作计划|实施方案|提纲|发言稿|主持词|致辞|讲话稿|汇报材料|调研报告"
)
_DOC_TYPE_KEYWORD_RE = re.compile(
    r"对照检查|述职报告|工作总结|工作计划|实施方案|提纲|发言稿"
    r"|主持词|致辞|讲话稿|汇报材料|调研报告"
    r"|汇报|总结|方案|报告|要点|计划|规划|意见|通知|通报"
    r"|请示|批复|函|纪要|公报|条例|规定|办法|细则"
)


def has_title_keyword(text: str) -> bool:
    """传入标题候选文本，返回是否包含旧 scorer 使用的强标题关键词。"""
    return bool(_TITLE_KEYWORD_RE.search(text or ""))


def has_doc_type_keyword(text: str) -> bool:
    """传入文首标题文本，返回是否包含可支撑职务姓名行的文种关键词。"""
    return bool(_DOC_TYPE_KEYWORD_RE.search(text or ""))


def starts_report_heading(text: str) -> bool:
    """传入去除编号后的文本，返回是否以报告回顾类标题起始语开头。"""
    return (text or "").startswith(REPORT_HEADING_STARTS)


def starts_report_heading_or_addressing(text: str) -> bool:
    """传入段落文本，返回是否为报告回顾标题或常见称呼起始。"""
    return (text or "").startswith((*REPORT_HEADING_STARTS, "各位委员", "各位同志"))


def detect_legacy_doc_type(title_texts: list[str] | tuple[str, ...]) -> str:
    """传入旧 importer 收集的标题文本列表，返回兼容旧链路的文种字符串。"""
    combined = " ".join(title_texts)
    if "报告" in combined or "工作回顾" in combined:
        return "REPORT"
    return "NORMAL"


def legacy_report_heading_score(text: str, prefix: str = "") -> tuple[int, bool]:
    """传入报告标题文本和已识别编号前缀，返回候选分和是否需要标题正文拆分。"""
    value = text or ""
    body = value[len(prefix):].lstrip() if prefix else value
    if not starts_report_heading(body):
        return 0, False
    period = value.find("。")
    heading_part = value[:period] if period > 0 else value
    if len(heading_part) > 50:
        return 0, False
    return 95, period > 0


def legacy_title2_score(
    text: str,
    *,
    document_mode: str,
    has_seen_body: bool,
    previous_type: str | None,
    contains_colon: bool,
    has_numbering: bool,
) -> int:
    """传入正文区标题候选和结构事实，返回旧 importer title2 候选分。"""
    value = text or ""
    if not has_seen_body and document_mode != "REPORT":
        return 0
    if len(value) >= 28:
        return 0
    if contains_colon:
        return 0
    if starts_report_heading_or_addressing(value):
        return 0
    if has_numbering:
        return 0
    if previous_type == "date_line":
        return 0
    if "。" in value:
        return 0
    return 95


def legacy_glossary_title_score(text: str, *, title2_score: int) -> int:
    """传入当前文本和 title2 分值，返回旧 importer 名词解释标题候选分。"""
    value = text or ""
    if title2_score > 0 and ("名词解释" in value or "注释" in value):
        return title2_score
    return 0


def legacy_glossary_item_score(
    text: str,
    *,
    glossary_mode: bool,
    numbering_type: str | None,
    prefix: str | None,
    contains_colon: bool,
) -> tuple[int, dict, str]:
    """传入 glossary 状态、编号和冒号事实，返回旧 importer 条目分值、meta 和前缀。"""
    value = text or ""
    output_prefix = prefix or ""
    if not glossary_mode:
        return 0, {}, ""
    if numbering_type == "heading3":
        body = value[len(output_prefix):].lstrip()
    else:
        if not contains_colon or len(value) < 4:
            return 0, {}, ""
        output_prefix = ""
        body = value
    colon_pos = -1
    for mark in ("：", ":"):
        colon_pos = body.find(mark)
        if colon_pos > 0:
            break
    return 90, {"glossary_item": True, "colon_pos": colon_pos if colon_pos > 0 else -1}, output_prefix


def legacy_report_addressing_score(text: str) -> int:
    """传入报告类称呼文本，返回旧 importer 报告称呼候选分。"""
    value = text or ""
    if not value.startswith(("各位委员", "各位同志")):
        return 0
    if len(value) > 25:
        return 0
    return 120


def legacy_heading_addressing_score(
    text: str,
    previous_type: str | None,
    *,
    has_seen_real_body: bool,
) -> int:
    """传入正文开始前称呼文本和上一类型，返回旧 importer 主送机关候选分。"""
    value = text or ""
    if has_seen_real_body:
        return 0
    if not (previous_type or "").startswith("heading"):
        return 0
    if not value.rstrip().endswith(("：", ":")):
        return 0
    return 110
