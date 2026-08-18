"""DOCX 分节和页眉页脚关系的物理导入辅助。"""

from __future__ import annotations

import copy

from docxtool.document.models import DocumentData


def extract_paragraph_sectPr(paragraph):
    """传入 python-docx 段落对象，返回该段落携带的分节属性副本或 None。"""
    from docx.oxml.ns import qn as _qn

    pPr = paragraph._element.find(_qn("w:pPr"))
    if pPr is None:
        return None
    sectPr = pPr.find(_qn("w:sectPr"))
    return copy.deepcopy(sectPr) if sectPr is not None else None


def collect_section_header_footer_parts(doc, sectPr, data: DocumentData) -> None:
    """传入源文档、分节属性和文档数据，记录该分节引用的页眉页脚关系部件。"""
    if sectPr is None:
        return

    from docx.oxml.ns import qn as _qn

    for tag in ("w:headerReference", "w:footerReference"):
        for ref in sectPr.findall(_qn(tag)):
            rel_id = ref.get(_qn("r:id"))
            if not rel_id or rel_id in data.section_relationship_parts:
                continue
            related = doc.part.related_parts.get(rel_id)
            if related is not None:
                data.section_relationship_parts[rel_id] = related
