"""文首标题元数据识别证据。"""

from __future__ import annotations

import re

from docxtool.document.recognition.document_mode import (
    has_doc_type_keyword,
    has_title_keyword,
    starts_report_heading_or_addressing,
)

_ROLE_KEYWORD_RE = re.compile(
    r"局长|主任|书记|主席|部长|处长|科长|司长|厅长|市长|县长"
    r"|区长|镇长|乡长|院长|校长|政委|总工|组长|队长|秘书长"
    r"|委员|常委|召集人|负责人|联系人|审定人|审核人|签发人"
)
_SPEECH_TITLE_RE = re.compile(r"发言|讲话|致辞|主持词")
_ROLE_NAME_WITH_GAP_RE = re.compile(r"[\u4e00-\u9fff、，,·]{2,28}\s{2,}[\u4e00-\u9fff·]{2,6}")
_ROLE_KEYWORD_WITH_NAME_RE = re.compile(r"[\u4e00-\u9fff、，,·]{2,28}\s+[\u4e00-\u9fff·]{2,6}")
_BARE_CHINESE_NAME_RE = re.compile(r"[\u4e00-\u9fff]{2,6}")
_YEAR_LINE_RE = re.compile(r"\d{4}年")
_YEAR_ANNUAL_RE = re.compile(r"\d{4}年度")
_SENTENCE_END_RE = re.compile(r"[。！？；]$")
_SENTENCE_MARK_RE = re.compile(r"[。！？；]")
_SPACED_TEXT_RE = re.compile(r"\S\s{2,}\S")


def legacy_title_score(
    text: str,
    previous_type: str | None,
    *,
    has_seen_body: bool,
    contains_colon: bool,
    has_numbering: bool,
) -> int:
    """传入当前文本和文首结构事实，返回旧 importer 主标题候选分。"""
    value = text or ""
    if has_seen_body:
        return 0
    if previous_type:
        return 0
    max_length = 60 if has_title_keyword(value) else 40
    if len(value) >= max_length and (len(value) > 100 or _SENTENCE_MARK_RE.search(value)):
        return 0
    if contains_colon or has_numbering:
        return 0
    if value.startswith("（"):
        return 0
    return 100


def legacy_title_cont_score(
    text: str,
    previous_type: str | None,
    *,
    has_seen_body: bool,
    contains_colon: bool,
    has_numbering: bool,
) -> int:
    """传入当前文本和上一结构事实，返回旧 importer 标题续行候选分。"""
    value = text or ""
    if has_seen_body:
        return 0
    if previous_type not in ("title", "title_cont", "date_line", "author_line"):
        return 0
    if len(value) >= 40:
        return 0
    if _SENTENCE_END_RE.search(value):
        return 0
    if contains_colon or has_numbering:
        return 0
    if value.startswith("（"):
        return 0
    if _SPACED_TEXT_RE.search(value):
        return 0
    if has_title_keyword(value):
        return 90
    if _YEAR_ANNUAL_RE.search(value):
        return 90
    if _YEAR_LINE_RE.search(value):
        return 0
    return 90


def legacy_date_line_score(
    text: str,
    previous_type: str | None,
    *,
    has_seen_body: bool,
    has_numbering: bool,
) -> int:
    """传入当前文本、上一类型和正文/编号事实，返回旧 importer 日期行候选分。"""
    value = text or ""
    if has_seen_body:
        return 0
    if previous_type not in ("title", "title_cont", "role_name", "author_line"):
        return 0
    if has_numbering:
        return 0
    if len(value) >= 50:
        return 0
    if has_title_keyword(value):
        return 0
    if not (value.startswith("（") or _YEAR_LINE_RE.search(value)):
        return 0
    return 85


def legacy_author_line_score(
    text: str,
    previous_type: str | None,
    *,
    has_seen_body: bool,
    contains_colon: bool,
    has_numbering: bool,
) -> int:
    """传入当前文本、上一类型和结构事实，返回旧 importer 署名行候选分。"""
    value = text or ""
    if has_seen_body:
        return 0
    if previous_type != "date_line":
        return 0
    if len(value) >= 20:
        return 0
    if contains_colon or has_numbering:
        return 0
    if value.startswith("（") or starts_report_heading_or_addressing(value):
        return 0
    if _SPACED_TEXT_RE.search(value):
        return 0
    return 80


def legacy_role_name_score(text: str, previous_title: str, *, contains_colon: bool) -> int:
    """传入当前短行、上一标题和冒号事实，返回旧 importer 职务姓名候选分。"""
    value = text or ""
    role_name_match = _ROLE_NAME_WITH_GAP_RE.fullmatch(value)
    role_keyword_match = _ROLE_KEYWORD_WITH_NAME_RE.fullmatch(value)
    if len(value) >= 20 and not role_name_match:
        return 0
    if contains_colon:
        return 0
    if role_name_match or re.search(r"\S\s{2,}\S", value):
        return 80
    if _ROLE_KEYWORD_RE.search(value) and role_keyword_match:
        return 110
    if _ROLE_KEYWORD_RE.search(value) and not re.search(r"\s", value):
        return 95 if _SPEECH_TITLE_RE.search(previous_title or "") else 80
    if _SPEECH_TITLE_RE.search(previous_title or "") and _BARE_CHINESE_NAME_RE.fullmatch(value):
        return 92
    if has_doc_type_keyword(previous_title) and len(value) < 20 and not contains_colon:
        return 75
    return 0
