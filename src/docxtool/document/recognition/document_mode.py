"""Shared document-mode and small structural evidence helpers."""

from __future__ import annotations

import re

# “报告”本身是普通公文文种；只有工作报告/工作回顾采用专用报告体例。
REPORT_DOCUMENT_TITLE_MARKERS = ("工作报告", "工作回顾")
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
