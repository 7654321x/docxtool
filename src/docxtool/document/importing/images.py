"""DOCX 段落图片和题注的物理事实判断。"""

from __future__ import annotations

import re


_OBJECT_CAPTION_RE = re.compile(
    r"^(?:表|图)\s*(?:(?:[0-9一二三四五六七八九十百]+(?:[-—._、][0-9一二三四五六七八九十百]+)*).*|[:：].*|)$"
)


def is_object_caption(paragraph) -> bool:
    """传入 python-docx 段落对象，返回该段是否像表格或图片下方的题注行。"""
    text = paragraph.text.strip()
    style_name = (paragraph.style.name or "") if paragraph.style else ""
    return bool(text and (is_object_caption_text(text) or style_name.lower() == "caption" or "题注" in style_name))


def is_object_caption_text(text: str) -> bool:
    """传入纯文本，返回该文本是否符合表/图题注编号形态。"""
    return bool(_OBJECT_CAPTION_RE.match((text or "").strip()))


def is_standalone_image_paragraph(paragraph) -> bool:
    """传入 python-docx 段落对象，返回该段是否只有图片对象而没有可见正文文字。"""
    return not paragraph.text.strip()


def contains_visible_image(paragraph_element) -> bool:
    """传入段落 OOXML 元素，返回其中是否包含真实可见的图片或旧式 pict 对象。"""
    picts = paragraph_element.findall(
        './/{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pict'
    )
    if picts:
        return True

    drawings = paragraph_element.findall(
        './/{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing'
    )
    for drawing in drawings:
        extents = [element for element in drawing.iter() if element.tag.endswith('}extent')]
        if not extents:
            return True
        for extent in extents:
            try:
                if int(extent.get('cx', '0')) > 0 and int(extent.get('cy', '0')) > 0:
                    return True
            except ValueError:
                return True
    return False
