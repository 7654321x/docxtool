"""Paragraph style-id and renderer invariant helpers.

本模块只负责输出 DOCX 段落的样式 ID、keepNext 标记和渲染后正文
不变量检查。它不决定段落类型，只把已经确定的 type_id 映射到
Renderer 的 DCT 样式。
"""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from docxtool.document.diagnostics.logging import logger


STYLE_PROFILE_DOCXTOOL = "docxtool"
STYLE_PROFILE_WPS_BUILTIN = "wps_builtin"
_STYLE_PROFILES = {STYLE_PROFILE_DOCXTOOL, STYLE_PROFILE_WPS_BUILTIN}


TYPE_TO_STYLE_ID: dict[str, str] = {
    "title": "DCT-Title",
    "title_cont": "DCT-Title",
    "embedded_document_title": "DCT-Title",
    "dispatch_number": "DCT-DocumentNumber",
    "meeting_meta": "DCT-Body",
    "meeting_title_meta": "DCT-Author",
    "date_line": "DCT-Date",
    "author_line": "DCT-Author",
    "role_name": "DCT-RoleName",
    "heading1": "DCT-Heading1",
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

_WPS_BUILTIN_TYPE_TO_STYLE_ID: dict[str, str] = {
    "meeting_meta": "Normal",
    "heading1": "Heading1",
    "heading2": "Heading2",
    "title2": "Heading2",
    "heading3": "Heading3",
    "heading4": "Heading4",
    "body": "Normal",
}

_WPS_REPLACED_DCT_STYLE_IDS = {
    "DCT-Body",
    "DCT-Heading1",
    "DCT-Heading2",
    "DCT-Heading3",
    "DCT-Heading4",
}


def normalize_style_profile(style_profile: str | None) -> str:
    """校验样式 profile；传入可选值，返回规范名称或立即失败。"""
    resolved = str(style_profile or STYLE_PROFILE_DOCXTOOL).strip().lower()
    if resolved not in _STYLE_PROFILES:
        raise ValueError("WPS_STYLE_PROFILE_INVALID")
    return resolved


def style_id_for_type(
    type_id: str,
    style_profile: str = STYLE_PROFILE_DOCXTOOL,
) -> str:
    """映射段落类型到样式 ID；传入类型和 profile，返回最终样式 ID。"""
    resolved_profile = normalize_style_profile(style_profile)
    if resolved_profile == STYLE_PROFILE_WPS_BUILTIN:
        style_id = _WPS_BUILTIN_TYPE_TO_STYLE_ID.get(type_id)
        if style_id is not None:
            return style_id
    style_id = TYPE_TO_STYLE_ID.get(type_id)
    if style_id is None:
        fallback = (
            "Normal"
            if resolved_profile == STYLE_PROFILE_WPS_BUILTIN
            else "DCT-Body"
        )
        logger.warning(
            "[渲染] 未知段落类型 %r，显式使用正文样式 %s",
            type_id,
            fallback,
        )
        return fallback
    return style_id


def set_paragraph_style_id(paragraph, style_id: str) -> None:
    """写入段落样式 ID；传入 paragraph 和样式 ID，返回 None。"""
    properties = paragraph._element.get_or_add_pPr()
    old = properties.find(qn("w:pStyle"))
    if old is not None:
        properties.remove(old)
    paragraph_style = OxmlElement("w:pStyle")
    paragraph_style.set(qn("w:val"), style_id)
    properties.insert(0, paragraph_style)


def set_keep_with_next(paragraph) -> None:
    """设置与下段同页；传入 paragraph，写入 keepNext/keepLines 后返回 None。"""
    properties = paragraph._element.get_or_add_pPr()
    _set_unique(properties, qn("w:keepNext"), OxmlElement("w:keepNext"))
    _set_unique(properties, qn("w:keepLines"), OxmlElement("w:keepLines"))


def paragraph_style_id(paragraph) -> str:
    """读取段落样式 ID；传入 paragraph，返回样式 ID 或空字符串。"""
    properties = paragraph._element.pPr
    if properties is None:
        return ""
    paragraph_style = properties.find(qn("w:pStyle"))
    return paragraph_style.get(qn("w:val")) if paragraph_style is not None else ""


def remove_paragraph_numbering(paragraph) -> bool:
    """移除 Word 原生编号；传入 paragraph，删除成功返回 True。"""
    properties = paragraph._element.pPr
    if properties is None:
        return False
    numbering = properties.find(qn("w:numPr"))
    if numbering is None:
        return False
    properties.remove(numbering)
    return True


def enforce_body_paragraph_invariants(
    document,
    protected_elements=None,
    *,
    style_profile: str = STYLE_PROFILE_DOCXTOOL,
) -> dict[str, int]:
    """修复输出正文段不变量；传入 Document 和保护元素集合，返回统计字典。"""
    resolved_profile = normalize_style_profile(style_profile)
    fallback_count = 0
    numpr_removed = 0
    protected_elements = protected_elements or set()
    for paragraph in document.paragraphs:
        if paragraph._p in protected_elements:
            continue
        if remove_paragraph_numbering(paragraph):
            numpr_removed += 1
        if not paragraph.text.strip():
            continue
        style_id = paragraph_style_id(paragraph)
        if _is_managed_style_id(style_id, resolved_profile):
            continue
        set_paragraph_style_id(
            paragraph,
            style_id_for_type("body", resolved_profile),
        )
        fallback_count += 1
    return {"fallback_count": fallback_count, "numpr_removed": numpr_removed}


def _is_managed_style_id(style_id: str, style_profile: str) -> bool:
    """判断输出样式是否属于当前 profile；传入 ID 和 profile，返回布尔值。"""
    if style_profile == STYLE_PROFILE_DOCXTOOL:
        return style_id.startswith("DCT-")
    if style_id in {"Normal", "Heading1", "Heading2", "Heading3", "Heading4"}:
        return True
    return style_id.startswith("DCT-") and style_id not in _WPS_REPLACED_DCT_STYLE_IDS


def is_standalone_keep_heading(paragraph_data, next_paragraph_data, rendered_text: str) -> bool:
    """判断是否应与下段同页；传入段落数据和渲染文本，返回布尔值。"""
    del next_paragraph_data, rendered_text
    return getattr(paragraph_data, "type_id", "") in {"attachment_page_mark", "attachment_title"}


def _set_unique(properties, tag, element) -> None:
    """替换同名子节点；传入父节点、标签和新节点，返回 None。"""
    old = properties.find(tag)
    if old is not None:
        properties.remove(old)
    properties.append(element)
