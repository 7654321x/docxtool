"""Managed official-document letterheads in the first-page body flow."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from lxml import etree
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import CONTENT_TYPE as CT, RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.shared import Cm, Pt, RGBColor

from docxtool.document.engine.style_catalog import ensure_letterhead_styles
from docxtool.document.letterhead_config import normalize_letterhead_config
from docxtool.document.style_config import PageSettings, StyleRule


MANAGED_PROPERTY = "DocxtoolLetterheadVersion"
MANAGED_VERSION = "1"
LETTERHEAD_STYLE_IDS = (
    "DCT-LetterheadMark",
    "DCT-DocumentNumber",
    "DCT-SignerLine",
    "DCT-LetterheadSeparator",
)
_LETTERHEAD_STYLE_NAMES = {
    "DCT-LetterheadMark": "Docxtool Letterhead Mark",
    "DCT-DocumentNumber": "Docxtool Document Number",
    "DCT-SignerLine": "Docxtool Signer Line",
    "DCT-LetterheadSeparator": "Docxtool Letterhead Separator",
}
WARNING_EXTERNAL = "LETTERHEAD_SKIPPED_EXISTING_EXTERNAL"
WARNING_UNKNOWN = "LETTERHEAD_SKIPPED_EXISTING_UNKNOWN"
_DOCUMENT_NUMBER_RE = re.compile(r"[^\s〔〕]{1,40}〔\d{4}〕\d+号")
_OBJECT_CAPTION_RE = re.compile(r"^(?:表|图)\s*[0-9一二三四五六七八九十百]+")
_CUSTOM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
_VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
_CUSTOM_FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"


@dataclass(frozen=True)
class LetterheadDetection:
    status: str = "none"
    protected_body_indexes: tuple[int, ...] = ()
    details: tuple[str, ...] = ()


@dataclass
class LetterheadResult:
    action: str
    detection: str
    warnings: list[str] = field(default_factory=list)
    managed_paragraphs: int = 0
    protected_elements: list[object] = field(default_factory=list)


def _style_id(element) -> str:
    value = element.find("./" + qn("w:pPr") + "/" + qn("w:pStyle"))
    return value.get(qn("w:val"), "") if value is not None else ""


def _paragraph_text(element) -> str:
    return "".join(node.text or "" for node in element.iter(qn("w:t"))).strip()


def _has_visible_drawing(element) -> bool:
    if any(node.tag in {qn("w:pict"), qn("w:object")} or node.tag.endswith("}shape") for node in element.iter()):
        return True
    for drawing in element.iter(qn("w:drawing")):
        extents = [node for node in drawing.iter() if node.tag.endswith("}extent")]
        if not extents:
            return True
        for extent in extents:
            try:
                if int(extent.get("cx", "0")) > 0 and int(extent.get("cy", "0")) > 0:
                    return True
            except ValueError:
                return True
    return False


def _has_red_text(element) -> bool:
    for color in element.iter(qn("w:color")):
        if (color.get(qn("w:val"), "") or "").upper() in {"FF0000", "C00000", "ED1C24"}:
            return True
    return False


def _has_red_bottom_border(element) -> bool:
    bottom = element.find("./" + qn("w:pPr") + "/" + qn("w:pBdr") + "/" + qn("w:bottom"))
    if bottom is None:
        return False
    return (bottom.get(qn("w:color"), "") or "").upper() in {"FF0000", "C00000", "ED1C24"}


def _custom_property_value(document, name: str) -> str | None:
    for part in document.part.package.parts:
        if str(part.partname) != "/docProps/custom.xml":
            continue
        try:
            root = etree.fromstring(part.blob)
        except (ValueError, etree.XMLSyntaxError):
            return None
        for prop in root.findall(f"{{{_CUSTOM_NS}}}property"):
            if prop.get("name") == name and len(prop):
                return (prop[0].text or "").strip()
    return None


def detect_letterhead(document) -> LetterheadDetection:
    """Conservatively classify an existing first-page body-flow letterhead."""

    body_children = [child for child in document._body._element.iterchildren() if child.tag != qn("w:sectPr")]
    top = body_children[:16]
    styles = [_style_id(child) if child.tag == qn("w:p") else "" for child in top]
    marker = _custom_property_value(document, MANAGED_PROPERTY) == MANAGED_VERSION
    try:
        start = styles.index("DCT-LetterheadMark")
        end = styles.index("DCT-LetterheadSeparator", start)
    except ValueError:
        start = end = -1
    if marker and start >= 0 and "DCT-DocumentNumber" in styles[start:end + 1]:
        allowed = set(LETTERHEAD_STYLE_IDS)
        if all(style in allowed for style in styles[start:end + 1]):
            return LetterheadDetection("managed", tuple(range(start, end + 1)), ("marker", "styles", "order"))

    texts = [_paragraph_text(child) if child.tag == qn("w:p") else "" for child in top]
    drawings = [
        index
        for index, child in enumerate(top)
        if _has_visible_drawing(child)
        and not (index + 1 < len(texts) and _OBJECT_CAPTION_RE.match(texts[index + 1]))
    ]
    red_marks = [
        index
        for index, child in enumerate(top)
        if child.tag == qn("w:p") and _has_red_text(child) and ("文件" in texts[index] or len(texts[index]) >= 4)
    ]
    number_indexes = [index for index, text in enumerate(texts) if _DOCUMENT_NUMBER_RE.search(text)]
    signer_indexes = [index for index, text in enumerate(texts) if "签发人" in text]
    separator_indexes = [
        index for index, child in enumerate(top) if child.tag == qn("w:p") and _has_red_bottom_border(child)
    ]
    signals = sorted(set(red_marks + number_indexes + signer_indexes + separator_indexes + drawings))
    if not signals:
        return LetterheadDetection()

    first = signals[0]
    if separator_indexes:
        last = next((index for index in separator_indexes if index >= first), max(signals))
    else:
        last = max(signals)
    protected = tuple(range(first, last + 1))
    if drawings:
        return LetterheadDetection("unknown", protected, ("complex-drawing",))
    recognized = bool(red_marks and number_indexes and (separator_indexes or signer_indexes))
    if recognized:
        return LetterheadDetection("recognized_external", protected, ("red-mark", "document-number"))
    return LetterheadDetection("unknown", protected, ("ambiguous-letterhead-signals",))


def _set_run_font(run, font_name: str, size_pt: float, *, color: str | None = None):
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), font_name)
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def _set_paragraph_style(paragraph, style_id: str) -> None:
    paragraph.style = _LETTERHEAD_STYLE_NAMES[style_id]
    paragraph.paragraph_format.first_line_indent = Pt(0)
    paragraph.paragraph_format.left_indent = Pt(0)
    paragraph.paragraph_format.right_indent = Pt(0)


def _document_number(config: dict) -> str:
    number = config["document_number"]
    return f"{number['agency_code']}〔{number['year']}〕{number['sequence']}号"


def _mark_lines(config: dict) -> list[tuple[str, bool]]:
    agencies = config["agencies"]
    if config["issuance_mode"] == "joint" and config["joint_mark_scope"] == "sponsor_only":
        agencies = agencies[:1]
    append_document = config["mark_display_mode"] == "agency_with_document"
    if len(agencies) == 1:
        name = agencies[0]["name"]
        return [(name if not append_document or name.endswith("文件") else name + "文件", False)]
    middle = (len(agencies) - 1) // 2
    return [
        (agency["name"], append_document and index == middle)
        for index, agency in enumerate(agencies)
    ]


def _add_mark_paragraphs(document, config: dict) -> list:
    paragraphs = []
    for text, add_document in _mark_lines(config):
        paragraph = document.add_paragraph()
        _set_paragraph_style(paragraph, "DCT-LetterheadMark")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(text)
        _set_run_font(run, "方正小标宋简体", 36, color="FF0000")
        if add_document:
            paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(13.5), WD_TAB_ALIGNMENT.RIGHT)
            label = paragraph.add_run("\t文件")
            _set_run_font(label, "方正小标宋简体", 36, color="FF0000")
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraphs.append(paragraph)
    return paragraphs


def _add_number_paragraph(document, config: dict):
    paragraph = document.add_paragraph()
    _set_paragraph_style(paragraph, "DCT-DocumentNumber")
    paragraph.alignment = (
        WD_ALIGN_PARAGRAPH.LEFT
        if config["document_direction"] == "upward"
        else WD_ALIGN_PARAGRAPH.CENTER
    )
    run = paragraph.add_run(_document_number(config))
    _set_run_font(run, "仿宋_GB2312", 16)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    return paragraph


def _add_signer_paragraphs(document, config: dict) -> list:
    if config["document_direction"] != "upward":
        return []
    paragraphs = []
    signers = config["signers"]
    for offset in range(0, len(signers), 2):
        row_signers = signers[offset:offset + 2]
        paragraph = document.add_paragraph()
        _set_paragraph_style(paragraph, "DCT-SignerLine")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        tab_positions = (Cm(7.2), Cm(11.4)) if len(row_signers) == 2 else (Cm(11.0),)
        for position in tab_positions:
            paragraph.paragraph_format.tab_stops.add_tab_stop(position, WD_TAB_ALIGNMENT.LEFT)
        for signer in row_signers:
            paragraph.add_run("\t")
            label = paragraph.add_run(f"{signer['label']}：")
            _set_run_font(label, "仿宋_GB2312", 16)
            name = paragraph.add_run(signer["name"])
            _set_run_font(name, "楷体_GB2312", 16)
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraphs.append(paragraph)
    return paragraphs


def _effective_line_pitch(settings: PageSettings) -> float:
    try:
        value = float(settings.line_spacing_value)
    except (TypeError, ValueError):
        value = 28.0
    return value if value > 0 else 28.0


def _add_separator(document, settings: PageSettings):
    paragraph = document.add_paragraph()
    _set_paragraph_style(paragraph, "DCT-LetterheadSeparator")
    ppr = paragraph._p.get_or_add_pPr()
    borders = ppr.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        ppr.append(borders)
    bottom = borders.find(qn("w:bottom"))
    if bottom is None:
        bottom = OxmlElement("w:bottom")
        borders.append(bottom)
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "0")
    bottom.set(qn("w:color"), "FF0000")
    paragraph.paragraph_format.space_before = Cm(0.4)
    paragraph.paragraph_format.space_after = Pt(2 * _effective_line_pitch(settings))
    paragraph.paragraph_format.line_spacing = Pt(1)
    return paragraph


def _first_title_element(document):
    for paragraph in document.paragraphs:
        if paragraph.style and paragraph.style.style_id == "DCT-Title":
            return paragraph._p
    body = document._body._element
    return next((child for child in body.iterchildren() if child.tag != qn("w:sectPr")), None)


def _move_before(elements: list, anchor) -> None:
    if anchor is None:
        return
    parent = anchor.getparent()
    index = parent.index(anchor)
    for element in elements:
        parent.remove(element)
        parent.insert(index, element)
        index += 1


def _set_managed_property(document) -> None:
    package = document.part.package
    custom_part = next((part for part in package.parts if str(part.partname) == "/docProps/custom.xml"), None)
    if custom_part is None:
        root = etree.Element(f"{{{_CUSTOM_NS}}}Properties", nsmap={None: _CUSTOM_NS, "vt": _VT_NS})
        custom_part = Part(
            PackURI("/docProps/custom.xml"),
            CT.OFC_CUSTOM_PROPERTIES,
            etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True),
            package,
        )
        package.relate_to(custom_part, RT.CUSTOM_PROPERTIES)
    else:
        root = etree.fromstring(custom_part.blob)
    existing = None
    max_pid = 1
    for prop in root.findall(f"{{{_CUSTOM_NS}}}property"):
        max_pid = max(max_pid, int(prop.get("pid", "1") or 1))
        if prop.get("name") == MANAGED_PROPERTY:
            existing = prop
    if existing is None:
        existing = etree.SubElement(root, f"{{{_CUSTOM_NS}}}property")
        existing.set("fmtid", _CUSTOM_FMTID)
        existing.set("pid", str(max_pid + 1))
        existing.set("name", MANAGED_PROPERTY)
    for child in list(existing):
        existing.remove(child)
    value = etree.SubElement(existing, f"{{{_VT_NS}}}i4")
    value.text = MANAGED_VERSION
    custom_part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def remove_managed_letterhead(document) -> int:
    removed = 0
    in_block = False
    for paragraph in list(document.paragraphs):
        style_id = paragraph.style.style_id if paragraph.style else ""
        if style_id == "DCT-LetterheadMark":
            in_block = True
        if in_block and style_id in LETTERHEAD_STYLE_IDS:
            paragraph._element.getparent().remove(paragraph._element)
            removed += 1
            if style_id == "DCT-LetterheadSeparator":
                break
        elif in_block:
            break
    return removed


def apply_letterhead(
    document,
    config,
    *,
    detection: LetterheadDetection | None = None,
    rules: list[StyleRule] | None = None,
    settings: PageSettings | None = None,
) -> LetterheadResult:
    normalized = normalize_letterhead_config(config)
    detection = detection or detect_letterhead(document)
    if not normalized["enabled"]:
        if detection.status == "managed":
            ensure_letterhead_styles(document, rules, settings or PageSettings())
            _set_managed_property(document)
        return LetterheadResult("preserved-disabled", detection.status)
    if detection.status == "recognized_external":
        return LetterheadResult("skipped-external", detection.status, [WARNING_EXTERNAL])
    if detection.status == "unknown":
        return LetterheadResult("skipped-unknown", detection.status, [WARNING_UNKNOWN])
    if detection.status == "managed" and not normalized["replace_managed"]:
        ensure_letterhead_styles(document, rules, settings or PageSettings())
        _set_managed_property(document)
        return LetterheadResult("preserved-managed", detection.status)
    if detection.status == "managed":
        remove_managed_letterhead(document)
    resolved_settings = settings or PageSettings()
    ensure_letterhead_styles(document, rules, resolved_settings)
    paragraphs = _add_mark_paragraphs(document, normalized)
    paragraphs.append(_add_number_paragraph(document, normalized))
    paragraphs.extend(_add_signer_paragraphs(document, normalized))
    paragraphs.append(_add_separator(document, resolved_settings))
    elements = [paragraph._p for paragraph in paragraphs]
    _move_before(elements, _first_title_element(document))
    _set_managed_property(document)
    return LetterheadResult(
        "replaced" if detection.status == "managed" else "generated",
        detection.status,
        managed_paragraphs=len(paragraphs),
        protected_elements=elements,
    )


__all__ = [
    "LETTERHEAD_STYLE_IDS",
    "LetterheadDetection",
    "LetterheadResult",
    "WARNING_EXTERNAL",
    "WARNING_UNKNOWN",
    "apply_letterhead",
    "detect_letterhead",
    "remove_managed_letterhead",
]
