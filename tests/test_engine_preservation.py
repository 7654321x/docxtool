from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from docxtool.document.engine.preservation import (
    append_body_element,
    sanitize_relationship_xml,
    set_object_caption_zero_spacing,
)


class _ExternalRel:
    """测试用外部关系对象，只提供清理函数需要读取的字段。"""

    rId = "rId9"
    reltype = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
    target_ref = "file:///C:/secret/image.png"
    is_external = True


def test_sanitize_relationship_xml_removes_disallowed_external_reference() -> None:
    """禁止外部关系应从 XML 属性移除，并只记录脱敏目标。"""
    xml = (
        b'<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        b'r:id="rId9"><w:r><w:t>text</w:t></w:r></w:p>'
    )
    removed: list[dict] = []

    cleaned = sanitize_relationship_xml(xml, [_ExternalRel()], removed)

    assert b"rId9" not in cleaned
    assert removed == [
        {
            "allowed": False,
            "relationship_type": "image",
            "sanitized_target": "file://[redacted]",
            "scheme": "file",
            "reason_code": "EXTERNAL_RELATIONSHIP_TYPE_NOT_ALLOWED",
        }
    ]


def test_append_body_element_inserts_before_body_section_properties() -> None:
    """追加保留对象时应插在正文 sectPr 前，保持 Word body XML 合法。"""
    doc = Document()
    paragraph = OxmlElement("w:p")

    append_body_element(doc, paragraph)

    children = list(doc.element.body)
    assert children[-2] is paragraph
    assert children[-1].tag == qn("w:sectPr")


def test_set_object_caption_zero_spacing_only_normalizes_spacing() -> None:
    """题注保留对象只归零段前段后，不删除原段落属性。"""
    paragraph = OxmlElement("w:p")
    p_pr = OxmlElement("w:pPr")
    keep_next = OxmlElement("w:keepNext")
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), "240")
    spacing.set(qn("w:after"), "120")
    spacing.set(qn("w:beforeAutospacing"), "1")
    p_pr.append(keep_next)
    p_pr.append(spacing)
    paragraph.append(p_pr)

    set_object_caption_zero_spacing(paragraph)

    assert p_pr.find(qn("w:keepNext")) is keep_next
    assert spacing.get(qn("w:before")) == "0"
    assert spacing.get(qn("w:after")) == "0"
    assert spacing.get(qn("w:beforeLines")) == "0"
    assert spacing.get(qn("w:afterLines")) == "0"
    assert spacing.get(qn("w:beforeAutospacing")) is None
