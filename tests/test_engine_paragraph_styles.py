from types import SimpleNamespace

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from docxtool.document.engine.paragraph_styles import (
    enforce_body_paragraph_invariants,
    is_standalone_keep_heading,
    paragraph_style_id,
    remove_paragraph_numbering,
    set_keep_with_next,
    set_paragraph_style_id,
    style_id_for_type,
)


def test_style_id_for_type_maps_known_types_and_falls_back_to_body() -> None:
    assert style_id_for_type("heading1") == "DCT-Heading1"
    assert style_id_for_type("attachment_note_item") == "DCT-AttachmentNoteItem"
    assert style_id_for_type("unknown_type") == "DCT-Body"


def test_set_and_read_paragraph_style_id_replaces_existing_style() -> None:
    doc = Document()
    paragraph = doc.add_paragraph("测试")

    set_paragraph_style_id(paragraph, "DCT-Body")
    set_paragraph_style_id(paragraph, "DCT-Heading1")

    properties = paragraph._element.get_or_add_pPr()
    styles = properties.findall(qn("w:pStyle"))
    assert len(styles) == 1
    assert paragraph_style_id(paragraph) == "DCT-Heading1"


def test_set_keep_with_next_writes_single_keep_nodes() -> None:
    doc = Document()
    paragraph = doc.add_paragraph("附件")

    set_keep_with_next(paragraph)
    set_keep_with_next(paragraph)

    properties = paragraph._element.get_or_add_pPr()
    assert len(properties.findall(qn("w:keepNext"))) == 1
    assert len(properties.findall(qn("w:keepLines"))) == 1


def test_remove_paragraph_numbering_removes_numpr_once() -> None:
    doc = Document()
    paragraph = doc.add_paragraph("列表")
    properties = paragraph._element.get_or_add_pPr()
    properties.append(OxmlElement("w:numPr"))

    assert remove_paragraph_numbering(paragraph) is True
    assert remove_paragraph_numbering(paragraph) is False


def test_enforce_body_paragraph_invariants_skips_protected_elements() -> None:
    doc = Document()
    protected = doc.add_paragraph("受保护")
    fallback = doc.add_paragraph("普通正文")

    stats = enforce_body_paragraph_invariants(doc, {protected._p})

    assert stats == {"fallback_count": 1, "numpr_removed": 0}
    assert paragraph_style_id(protected) == ""
    assert paragraph_style_id(fallback) == "DCT-Body"


def test_is_standalone_keep_heading_only_allows_attachment_mark_and_title() -> None:
    assert is_standalone_keep_heading(SimpleNamespace(type_id="attachment_title"), None, "") is True
    assert is_standalone_keep_heading(SimpleNamespace(type_id="heading1"), None, "") is False
