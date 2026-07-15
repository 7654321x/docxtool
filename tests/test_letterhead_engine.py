import copy
import hashlib
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from docxtool.document.engine.core import export_doc
from docxtool.document.engine.letterhead import (
    WARNING_EXTERNAL,
    WARNING_UNKNOWN,
    apply_letterhead,
    detect_letterhead,
)
from docxtool.document.importer import DocumentData, ParagraphData, ParagraphFeatures, DocxImporter
from docxtool.document.letterhead_config import default_letterhead_config
from docxtool.document.style_config import PageSettings, StyleRule
from docxtool.security import validate_docx_integrity


def rules():
    return [StyleRule.default_for_row(index) for index in range(24)]


def config(**changes):
    value = default_letterhead_config()
    value.update(
        {
            "enabled": True,
            "agencies": [
                {"id": "agency-1", "name": "测试机关", "short_name": "", "role": "sponsor", "order": 1}
            ],
            "document_number": {"agency_code": "测发", "year": 2026, "sequence": 12},
        }
    )
    value.update(changes)
    return value


def data(source: Path | None = None):
    return DocumentData(
        filepath=str(source or "generated.docx"),
        paragraphs=[
            ParagraphData("公文标题", "title", "公文标题", ParagraphFeatures()),
            ParagraphData("正文内容。", "body", "正文内容。", ParagraphFeatures()),
        ],
    )


def export(tmp_path, letterhead, name="output.docx", source=None):
    output = tmp_path / name
    stats = export_doc(
        data(source), rules(), PageSettings(), str(output),
        page_number_enabled=False, letterhead_options=letterhead,
    )
    validate_docx_integrity(output)
    return output, stats


def style_ids(document):
    return [paragraph.style.style_id for paragraph in document.paragraphs]


def test_missing_null_and_disabled_do_not_generate(tmp_path):
    for index, value in enumerate((None, {**default_letterhead_config(), "enabled": False})):
        output, stats = export(tmp_path, value, f"disabled-{index}.docx")
        document = Document(output)
        assert "DCT-LetterheadMark" not in style_ids(document)
        assert [paragraph.text for paragraph in document.paragraphs if paragraph.text] == ["公文标题", "正文内容。"]
        assert stats["letterhead_action"] == "preserved-disabled"


def test_single_mark_document_number_separator_and_title_spacing(tmp_path):
    output, stats = export(tmp_path, config())
    document = Document(output)
    assert [paragraph.text for paragraph in document.paragraphs[:4]] == [
        "测试机关文件", "测发〔2026〕12号", "", "公文标题"
    ]
    assert style_ids(document)[:4] == [
        "DCT-LetterheadMark", "DCT-DocumentNumber", "DCT-LetterheadSeparator", "DCT-Title"
    ]
    assert stats["letterhead_action"] == "generated"
    assert document.paragraphs[2].paragraph_format.space_after.pt == 56
    with ZipFile(output) as archive:
        document_xml = etree.fromstring(archive.read("word/document.xml"))
        styles_xml = etree.fromstring(archive.read("word/styles.xml"))
        custom_xml = archive.read("docProps/custom.xml").decode("utf-8")
        assert document_xml.find(".//" + qn("w:pBdr") + "/" + qn("w:bottom")).get(qn("w:color")) == "FF0000"
        assert not document_xml.findall(".//" + qn("w:drawing"))
        assert not document_xml.findall(".//" + qn("w:pict"))
        assert not document_xml.findall(".//" + qn("w:object"))
        assert "DocxtoolLetterheadVersion" in custom_xml
        assert not any("header" in name and name.endswith(".xml") for name in archive.namelist())
        for style_id in (
            "DCT-LetterheadMark", "DCT-DocumentNumber", "DCT-SignerLine", "DCT-LetterheadSeparator"
        ):
            assert styles_xml.find(f".//{qn('w:style')}[@{qn('w:styleId')}='{style_id}']") is not None
        assert b"------" not in archive.read("word/document.xml")
    assert round(document.paragraphs[2].paragraph_format.space_before.cm, 1) == 0.4


def test_agency_only_and_name_ending_in_document_are_not_duplicated(tmp_path):
    output, _ = export(tmp_path, config(mark_display_mode="agency_only"), "agency-only.docx")
    assert Document(output).paragraphs[0].text == "测试机关"
    ending = config(agencies=[{"id": "agency-1", "name": "测试机关文件", "short_name": "", "role": "sponsor", "order": 1}])
    output2, _ = export(tmp_path, ending, "ending.docx")
    assert Document(output2).paragraphs[0].text == "测试机关文件"


def test_upward_multiple_signers_use_separate_runs_and_tabs(tmp_path):
    signers = [
        {"id": "signer-1", "agency_id": "agency-1", "name": "张三", "label": "签发人", "order": 1},
        {"id": "signer-2", "agency_id": "agency-1", "name": "李四", "label": "签发人", "order": 2},
        {"id": "signer-3", "agency_id": "agency-1", "name": "王五", "label": "签发人", "order": 3},
    ]
    output, _ = export(tmp_path, config(document_direction="upward", signers=signers), "upward.docx")
    document = Document(output)
    assert document.paragraphs[1].alignment == 0
    signer_paragraphs = [p for p in document.paragraphs if p.style.style_id == "DCT-SignerLine"]
    assert len(signer_paragraphs) == 2
    assert [p.text for p in signer_paragraphs] == ["\t签发人：张三\t签发人：李四", "\t签发人：王五"]
    assert signer_paragraphs[0].runs[1].text == "签发人："
    assert signer_paragraphs[0].runs[2].text == "张三"
    assert signer_paragraphs[0].runs[2].font.name == "楷体_GB2312"
    assert [round(stop.position.cm, 1) for stop in signer_paragraphs[0].paragraph_format.tab_stops] == [7.2, 11.4]


def test_downward_and_parallel_preserve_configured_signers_without_rendering_them(tmp_path):
    signers = [
        {"id": "signer-1", "agency_id": "agency-1", "name": "张三", "label": "签发人", "order": 1}
    ]
    for direction in ("downward", "parallel"):
        output, _ = export(
            tmp_path,
            config(document_direction=direction, signers=signers),
            f"{direction}.docx",
        )
        assert "DCT-SignerLine" not in style_ids(Document(output))


def test_joint_all_and_sponsor_only_preserve_sponsor_order_and_number(tmp_path):
    agencies = [
        {"id": "agency-2", "name": "联合机关乙", "short_name": "", "role": "joint", "order": 1},
        {"id": "agency-1", "name": "主办机关甲", "short_name": "", "role": "sponsor", "order": 2},
        {"id": "agency-3", "name": "联合机关丙", "short_name": "", "role": "joint", "order": 3},
    ]
    joint = config(issuance_mode="joint", agencies=agencies)
    output, _ = export(tmp_path, joint, "joint.docx")
    document = Document(output)
    marks = [p.text for p in document.paragraphs if p.style.style_id == "DCT-LetterheadMark"]
    assert marks == ["主办机关甲", "联合机关乙\t文件", "联合机关丙"]
    assert "测发〔2026〕12号" in [p.text for p in document.paragraphs]

    sponsor_only = copy.deepcopy(joint)
    sponsor_only["joint_mark_scope"] = "sponsor_only"
    output2, _ = export(tmp_path, sponsor_only, "sponsor-only.docx")
    marks2 = [p.text for p in Document(output2).paragraphs if p.style.style_id == "DCT-LetterheadMark"]
    assert marks2 == ["主办机关甲文件"]


def test_managed_output_is_detected_and_reprocessing_is_idempotent(tmp_path):
    first, _ = export(tmp_path, config(), "first.docx")
    first_data = DocxImporter().load(str(first), rules(), features={})
    assert first_data.letterhead_detection.status == "managed"
    second = tmp_path / "second.docx"
    second_stats = export_doc(
        first_data, rules(), PageSettings(), str(second),
        page_number_enabled=False, letterhead_options=config(),
    )
    assert second_stats["letterhead_action"] == "preserved-managed"
    assert style_ids(Document(second)).count("DCT-LetterheadMark") == 1
    assert detect_letterhead(Document(second)).status == "managed"

    replace = config(replace_managed=True, document_number={"agency_code": "测发", "year": 2026, "sequence": 99})
    replaced = tmp_path / "replaced.docx"
    replaced_stats = export_doc(
        first_data, rules(), PageSettings(), str(replaced),
        page_number_enabled=False, letterhead_options=replace,
    )
    assert replaced_stats["letterhead_action"] == "replaced"
    assert [p.text for p in Document(replaced).paragraphs].count("测发〔2026〕99号") == 1


def _external_document(path: Path):
    document = Document()
    mark = document.add_paragraph()
    mark.alignment = 1
    mark_run = mark.add_run("测试机关文件")
    mark_run.font.color.rgb = None
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "FF0000")
    mark_run._element.get_or_add_rPr().append(color)
    document.add_paragraph("测发〔2026〕3号")
    separator = document.add_paragraph()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:color"), "FF0000")
    borders.append(bottom)
    separator._p.get_or_add_pPr().append(borders)
    document.add_paragraph("外部公文标题")
    document.add_paragraph("正文内容。")
    document.save(path)


def test_external_letterhead_is_preserved_and_warned(tmp_path):
    source = tmp_path / "external.docx"
    _external_document(source)
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    imported = DocxImporter().load(str(source), rules(), features={})
    assert imported.letterhead_detection.status == "recognized_external"
    output = tmp_path / "external-output.docx"
    stats = export_doc(
        imported, rules(), PageSettings(), str(output),
        page_number_enabled=False, letterhead_options=config(),
    )
    assert stats["compatibility_warnings"] == [WARNING_EXTERNAL]
    assert [p.text for p in Document(output).paragraphs[:3]] == ["测试机关文件", "测发〔2026〕3号", ""]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before_hash


def test_unknown_complex_letterhead_is_preserved_and_warned():
    document = Document()
    paragraph = document.add_paragraph()
    paragraph._p.append(OxmlElement("w:drawing"))
    document.add_paragraph("公文标题")
    detection = detect_letterhead(document)
    assert detection.status == "unknown"
    result = apply_letterhead(document, config(), detection=detection, rules=rules(), settings=PageSettings())
    assert result.warnings == [WARNING_UNKNOWN]
    assert "DCT-LetterheadMark" not in style_ids(document)


def test_zero_size_drawing_and_captioned_image_are_not_letterhead_signals():
    zero_size = Document()
    paragraph = zero_size.add_paragraph("（三）普通段落。")
    drawing = OxmlElement("w:drawing")
    extent = OxmlElement("wp:extent")
    extent.set("cx", "100")
    extent.set("cy", "0")
    drawing.append(extent)
    paragraph._p.append(drawing)
    assert detect_letterhead(zero_size).status == "none"

    captioned = Document()
    image_paragraph = captioned.add_paragraph()
    drawing = OxmlElement("w:drawing")
    extent = OxmlElement("wp:extent")
    extent.set("cx", "100")
    extent.set("cy", "100")
    drawing.append(extent)
    image_paragraph._p.append(drawing)
    captioned.add_paragraph("图2结构示意图")
    assert detect_letterhead(captioned).status == "none"


def test_unknown_complex_letterhead_file_is_preserved_and_input_is_unchanged(tmp_path):
    source = tmp_path / "unknown.docx"
    document = Document()
    paragraph = document.add_paragraph()
    paragraph._p.append(OxmlElement("w:drawing"))
    document.add_paragraph("公文标题")
    document.add_paragraph("正文内容。")
    document.save(source)
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    imported = DocxImporter().load(str(source), rules(), features={})
    assert imported.letterhead_detection.status == "unknown"
    output = tmp_path / "unknown-output.docx"
    stats = export_doc(
        imported,
        rules(),
        PageSettings(),
        str(output),
        page_number_enabled=False,
        letterhead_options=config(),
    )

    assert stats["compatibility_warnings"] == [WARNING_UNKNOWN]
    assert Document(output).paragraphs[0]._p.find(".//" + qn("w:drawing")) is not None
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before_hash
