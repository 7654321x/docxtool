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
    "DCT-LetterheadSpacer",
    "DCT-LetterheadMark",
    "DCT-DocumentNumber",
    "DCT-SignerLine",
    "DCT-LetterheadSeparator",
)
_LETTERHEAD_STYLE_NAMES = {
    "DCT-LetterheadSpacer": "Docxtool Letterhead Spacer",
    "DCT-LetterheadMark": "Docxtool Letterhead Mark",
    "DCT-DocumentNumber": "Docxtool Document Number",
    "DCT-SignerLine": "Docxtool Signer Line",
    "DCT-LetterheadSeparator": "Docxtool Letterhead Separator",
}
WARNING_EXTERNAL = "LETTERHEAD_SKIPPED_EXISTING_EXTERNAL"
WARNING_UNKNOWN = "LETTERHEAD_SKIPPED_EXISTING_UNKNOWN"
_STANDARD_DOCUMENT_NUMBER_RE = re.compile(
    r"^[^\s，。；：:（）()《》“”]{1,24}〔\d{4}〕\d+号(?:签发人[：:].{1,80})?$"
)
_COMPATIBLE_DOCUMENT_NUMBER_RE = re.compile(
    r"^[^\s，。；：:（）()《》“”\[\]【】〔〕]{1,24}"
    r"(?:\[\d{4}\]|【\d{4}】|（\d{4}）|\(\d{4}\)|〔\d{4}〕)"
    r"第?\d+号(?:签发人[：:].{1,80})?$"
)
_SIGNER_LINE_RE = re.compile(r"^签发人[：:].{1,80}$")
_AGENCY_FILE_MARK_RE = re.compile(
    r"^(?!关于).{2,36}(?:委员会|人民政府|办公室|办公厅|党组|党委|委|办|局|厅|部|院|中心)文件$"
)
_AGENCY_NAME_RE = re.compile(
    r"^(?!关于).{2,36}(?:委员会|人民政府|办公室|办公厅|党组|党委|委|办|局|厅|部|院|中心)$"
)
_LEADING_METADATA_RE = re.compile(
    r"^(?:\d{6}|(?:绝密|机密|秘密)(?:★\d+(?:年|月|日)?)?|特提|特急|加急|平急)$"
)
_TITLE_SUFFIXES = (
    "决议",
    "决定",
    "命令",
    "令",
    "公报",
    "公告",
    "通告",
    "意见",
    "通知",
    "通报",
    "报告",
    "请示",
    "批复",
    "议案",
    "函",
    "纪要",
    "方案",
    "总结",
    "要点",
    "安排",
    "计划",
    "细则",
    "办法",
    "规定",
)
_OBJECT_CAPTION_RE = re.compile(r"^(?:表|图)\s*[0-9一二三四五六七八九十百]+")
_CUSTOM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
_VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
_CUSTOM_FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"
_MARK_FONT_SIZE_PT = 32


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
        if _is_red_color(color.get(qn("w:val"), "")):
            return True
    return False


def _is_red_color(value: str | None) -> bool:
    color = (value or "").strip().upper().lstrip("#")
    if not re.fullmatch(r"[0-9A-F]{6}", color):
        return False
    red, green, blue = (int(color[offset:offset + 2], 16) for offset in (0, 2, 4))
    return red >= 150 and red - green >= 55 and red - blue >= 55


def _paragraph_alignment(element) -> str:
    alignment = element.find("./" + qn("w:pPr") + "/" + qn("w:jc"))
    return (alignment.get(qn("w:val"), "") or "").lower() if alignment is not None else ""


def _max_direct_font_size_pt(element) -> float:
    values = []
    for size in element.iter(qn("w:sz")):
        try:
            values.append(int(size.get(qn("w:val"), "0")) / 2)
        except (TypeError, ValueError):
            continue
    return max(values, default=0.0)


def _is_letterhead_mark(element, text: str) -> bool:
    """Return whether a leading paragraph is a plausible agency mark.

    Existing documents can be badly formatted, so a red line containing the
    semantic ``文件`` marker remains usable even when its alignment or run sizes
    are inconsistent. Agency-only marks require the stronger visual shape.
    """

    compact = re.sub(r"\s+", "", text or "")
    if not compact or len(compact) > 80 or not _has_red_text(element):
        return False
    if "文件" in compact:
        if compact.startswith("关于"):
            return False
        return len(compact) >= 4
    return (
        4 <= len(compact) <= 40
        and _paragraph_alignment(element) in {"center", "both", "distribute"}
        and _max_direct_font_size_pt(element) >= 26
    )


def _is_semantic_agency_file_mark(text: str) -> bool:
    """Recognize a leading agency-name + 文件 line even if red formatting was lost."""

    compact = re.sub(r"\s+", "", text or "")
    return bool(_AGENCY_FILE_MARK_RE.fullmatch(compact))


def _is_semantic_agency_name(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return bool(_AGENCY_NAME_RE.fullmatch(compact))


def _has_red_separator_border(element) -> bool:
    borders = element.find("./" + qn("w:pPr") + "/" + qn("w:pBdr"))
    if borders is None:
        return False
    for edge_name in ("bottom", "top"):
        edge = borders.find(qn(f"w:{edge_name}"))
        if edge is not None and _is_red_color(edge.get(qn("w:color"), "")):
            return True
    return False


def _is_document_number_line(text: str) -> bool:
    return _document_number_kind(text) is not None


def _document_number_kind(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    if _STANDARD_DOCUMENT_NUMBER_RE.fullmatch(compact):
        return "standard"
    if _COMPATIBLE_DOCUMENT_NUMBER_RE.fullmatch(compact):
        return "compatible"
    return None


def _is_signer_line(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return bool(_SIGNER_LINE_RE.fullmatch(compact)) or (
        _is_document_number_line(compact) and "签发人" in compact
    )


def _is_blank_body_paragraph(element, text: str) -> bool:
    return element.tag == qn("w:p") and not text and not _has_visible_drawing(element)


def _is_leading_metadata(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return bool(_LEADING_METADATA_RE.fullmatch(compact))


def _looks_like_signer_continuation(text: str) -> bool:
    value = (text or "").strip()
    compact = re.sub(r"\s+", "", value)
    return bool(
        2 <= len(compact) <= 24
        and re.fullmatch(r"[\u3400-\u9fff·\s]+", value)
        and not compact.startswith("关于")
        and not compact.endswith(_TITLE_SUFFIXES)
        and not _is_semantic_agency_name(compact)
    )


def _looks_like_following_title(element, text: str) -> bool:
    """Return whether a non-letterhead paragraph plausibly starts the title."""

    compact = re.sub(r"\s+", "", text or "")
    if not (4 <= len(compact) <= 120):
        return False
    if compact.endswith(("：", ":")) or any(mark in compact for mark in "。！？；;"):
        return False
    if compact.startswith("关于") or compact.endswith(_TITLE_SUFFIXES):
        return True
    style_id = _style_id(element).lower()
    return (
        "title" in style_id
        or "标题" in style_id
        or _paragraph_alignment(element) == "center"
        or _max_direct_font_size_pt(element) >= 18
    )


def _has_following_header_signal(
    top: list[object],
    texts: list[str],
    mark_index: int,
    header_signal_indexes: set[int],
) -> bool:
    for index in range(mark_index + 1, min(len(top), mark_index + 13)):
        if index in header_signal_indexes:
            return True
        if not _is_blank_body_paragraph(top[index], texts[index]):
            return False
    return False


def _has_following_title(
    top: list[object],
    texts: list[str],
    mark_index: int,
    header_signal_indexes: set[int],
) -> bool:
    """Look past metadata for an independent title after an agency-file mark."""

    title_parts = []
    first_title_element = None
    for index in range(mark_index + 1, min(len(top), mark_index + 13)):
        if index in header_signal_indexes:
            continue
        if _is_blank_body_paragraph(top[index], texts[index]):
            continue
        if top[index].tag != qn("w:p") or _has_visible_drawing(top[index]):
            return False
        if first_title_element is None:
            first_title_element = top[index]
        title_parts.append(texts[index])
        combined = "".join(title_parts)
        if _looks_like_following_title(first_title_element, combined):
            return True
        if len(title_parts) >= 3 or any(mark in combined for mark in "。！？；;：:"):
            return False
    return False


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
    top = body_children[:32]
    styles = [_style_id(child) if child.tag == qn("w:p") else "" for child in top]
    marker = _custom_property_value(document, MANAGED_PROPERTY) == MANAGED_VERSION
    try:
        start = next(
            index
            for index, style in enumerate(styles)
            if style in {"DCT-LetterheadSpacer", "DCT-LetterheadMark"}
        )
        end = styles.index("DCT-LetterheadSeparator", start)
    except (StopIteration, ValueError):
        start = end = -1
    if marker and start >= 0 and "DCT-DocumentNumber" in styles[start:end + 1]:
        allowed = set(LETTERHEAD_STYLE_IDS)
        if all(style in allowed for style in styles[start:end + 1]):
            return LetterheadDetection("managed", tuple(range(start, end + 1)), ("marker", "styles", "order"))

    texts = [_paragraph_text(child) if child.tag == qn("w:p") else "" for child in top]
    visible_indexes = [
        index
        for index, child in enumerate(top)
        if texts[index] or _has_visible_drawing(child) or child.tag != qn("w:p")
    ]
    if not visible_indexes:
        return LetterheadDetection()
    first_visible = visible_indexes[0]

    drawings = [
        first_visible
        for child in top[first_visible:first_visible + 1]
        if _has_visible_drawing(child)
        and not (
            first_visible + 1 < len(texts)
            and _OBJECT_CAPTION_RE.match(texts[first_visible + 1])
        )
    ]
    raw_red_marks = [
        index
        for index, child in enumerate(top)
        if child.tag == qn("w:p") and _is_letterhead_mark(child, texts[index])
    ]
    raw_semantic_marks = [
        index
        for index, child in enumerate(top)
        if child.tag == qn("w:p") and _is_semantic_agency_file_mark(texts[index])
    ]
    number_kinds = {
        index: kind
        for index, text in enumerate(texts)
        if (kind := _document_number_kind(text)) is not None
    }
    number_indexes = list(number_kinds)
    signer_indexes = [index for index, text in enumerate(texts) if _is_signer_line(text)]
    separator_indexes = [
        index
        for index, child in enumerate(top)
        if (
            child.tag == qn("w:p")
            and _has_red_separator_border(child)
            and (
                not texts[index]
                or _is_document_number_line(texts[index])
                or _is_signer_line(texts[index])
            )
        )
    ]
    for signer_index in tuple(signer_indexes):
        following_separators = [index for index in separator_indexes if index > signer_index]
        if not following_separators:
            continue
        separator_index = min(following_separators)
        for index in range(signer_index + 1, separator_index):
            if _is_blank_body_paragraph(top[index], texts[index]):
                continue
            if top[index].tag != qn("w:p") or not _looks_like_signer_continuation(texts[index]):
                break
            signer_indexes.append(index)
    signer_indexes = sorted(set(signer_indexes))
    metadata_indexes = [index for index, text in enumerate(texts) if _is_leading_metadata(text)]
    raw_mark_indexes = sorted(set(raw_red_marks + raw_semantic_marks))
    non_mark_header_signals = set(number_indexes + signer_indexes + separator_indexes)
    mark_indexes = [
        index
        for index in raw_mark_indexes
        if _has_following_header_signal(top, texts, index, non_mark_header_signals)
        or _has_following_title(top, texts, index, non_mark_header_signals)
    ]
    joint_mark_indexes = []
    for mark_index in mark_indexes:
        for index in range(mark_index - 1, max(-1, mark_index - 9), -1):
            if _is_blank_body_paragraph(top[index], texts[index]):
                continue
            if top[index].tag != qn("w:p") or not _is_semantic_agency_name(texts[index]):
                break
            joint_mark_indexes.append(index)
    mark_indexes = sorted(set(mark_indexes + joint_mark_indexes))

    signal_kinds = {
        index: {
            kind
            for kind, indexes in (
                ("mark", mark_indexes),
                ("number", number_indexes),
                ("signer", signer_indexes),
                ("separator", separator_indexes),
                ("metadata", metadata_indexes),
                ("drawing", drawings),
            )
            if index in indexes
        }
        for index in sorted(
            set(mark_indexes + number_indexes + signer_indexes + separator_indexes + metadata_indexes + drawings)
        )
    }
    if first_visible not in signal_kinds:
        return LetterheadDetection()

    # Only consume a contiguous leading candidate block. A normal non-empty
    # paragraph ends detection, so unrelated red text or images later in the
    # first page can never widen the protected range.
    candidate_indexes = []
    for index in range(first_visible, len(top)):
        if index in signal_kinds:
            candidate_indexes.append(index)
            continue
        if _is_blank_body_paragraph(top[index], texts[index]):
            continue
        break

    candidate_set = set(candidate_indexes)
    candidate_numbers = [index for index in number_indexes if index in candidate_set]
    standard_candidate_numbers = [
        index for index in candidate_numbers if number_kinds[index] == "standard"
    ]
    compatible_candidate_numbers = [
        index for index in candidate_numbers if number_kinds[index] == "compatible"
    ]
    candidate_signers = [index for index in signer_indexes if index in candidate_set]
    candidate_separators = [index for index in separator_indexes if index in candidate_set]
    candidate_red_marks = [index for index in raw_red_marks if index in candidate_set]
    candidate_drawings = [index for index in drawings if index in candidate_set]
    kinds = set().union(*(signal_kinds[index] for index in candidate_indexes)) if candidate_indexes else set()

    complete_visual_header = bool(
        candidate_red_marks
        and standard_candidate_numbers
        and min(candidate_red_marks) <= min(standard_candidate_numbers)
    )
    number_separator_header = bool(
        standard_candidate_numbers
        and candidate_separators
        and min(standard_candidate_numbers) <= max(candidate_separators)
    )
    recognized = complete_visual_header or number_separator_header
    incomplete = bool(
        candidate_indexes
        and (
            kinds <= {"metadata", "number"}
            or kinds == {"mark"}
            or kinds <= {"metadata", "number", "signer"}
        )
        and bool(kinds & {"mark", "number"})
    )
    unknown = bool(
        incomplete
        or bool(compatible_candidate_numbers)
        or
        (candidate_drawings and len(kinds - {"drawing"}) >= 1)
        or (
            len(kinds) >= 2
            and kinds != {"number", "signer"}
            and not recognized
        )
    )
    if not recognized and not unknown:
        return LetterheadDetection()

    first = 0 if all(
        _is_blank_body_paragraph(top[index], texts[index])
        for index in range(first_visible)
    ) else first_visible
    if recognized:
        metadata_end = max(candidate_numbers + candidate_signers)
        trailing_separators = [
            index for index in candidate_separators if index >= metadata_end
        ]
        last = trailing_separators[0] if trailing_separators else metadata_end
    else:
        last = max(candidate_indexes)
    while last + 1 < len(top) and _is_blank_body_paragraph(top[last + 1], texts[last + 1]):
        last += 1
    protected = tuple(range(first, last + 1))

    if recognized:
        details = (
            ("red-mark", "document-number", "bounded-prefix")
            if complete_visual_header
            else ("document-number", "separator", "bounded-prefix")
        )
        return LetterheadDetection(
            "recognized_external",
            protected,
            details,
        )
    if compatible_candidate_numbers:
        details = ("compatible-document-number", "bounded-prefix")
    elif incomplete and kinds <= {"metadata", "number"}:
        details = ("incomplete-document-number", "bounded-prefix")
    elif incomplete and kinds == {"mark"}:
        details = ("incomplete-letterhead-mark", "following-title", "bounded-prefix")
    elif incomplete:
        details = ("incomplete-document-number-signer", "bounded-prefix")
    elif candidate_drawings:
        details = ("complex-drawing", "bounded-prefix")
    else:
        details = ("ambiguous-letterhead-signals", "bounded-prefix")
    return LetterheadDetection("unknown", protected, details)


def _set_run_font(
    run,
    font_name: str,
    size_pt: float,
    *,
    color: str | None = None,
):
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    rpr = run._element.get_or_add_rPr()
    rpr.rFonts.set(qn("w:eastAsia"), font_name)
    rpr.rFonts.set(qn("w:ascii"), "Times New Roman")
    rpr.rFonts.set(qn("w:hAnsi"), "Times New Roman")
    rpr.rFonts.set(qn("w:cs"), "Times New Roman")
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def _set_paragraph_style(paragraph, style_id: str) -> None:
    paragraph.style = _LETTERHEAD_STYLE_NAMES[style_id]
    paragraph.paragraph_format.first_line_indent = Pt(0)
    paragraph.paragraph_format.left_indent = Pt(0)
    paragraph.paragraph_format.right_indent = Pt(0)


def _set_paragraph_line_spacing(
    paragraph,
    *,
    before_lines: int = 0,
    after_lines: int = 0,
) -> None:
    """Write paragraph spacing in OOXML line units (hundredths of a line)."""

    spacing = paragraph._p.get_or_add_pPr().get_or_add_spacing()
    for attribute in ("before", "after"):
        spacing.attrib.pop(qn(f"w:{attribute}"), None)
    spacing.set(qn("w:beforeLines"), str(before_lines * 100))
    spacing.set(qn("w:afterLines"), str(after_lines * 100))


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
    paragraphs = _add_spacer_paragraphs(document, 3)
    for text, add_document in _mark_lines(config):
        paragraph = document.add_paragraph()
        _set_paragraph_style(paragraph, "DCT-LetterheadMark")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(text)
        _set_run_font(run, "方正小标宋简体", _MARK_FONT_SIZE_PT, color="FF0000")
        if add_document:
            paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(13.5), WD_TAB_ALIGNMENT.RIGHT)
            label = paragraph.add_run("\t文件")
            _set_run_font(label, "方正小标宋简体", _MARK_FONT_SIZE_PT, color="FF0000")
        _set_paragraph_line_spacing(paragraph)
        paragraphs.append(paragraph)
    paragraphs.extend(_add_spacer_paragraphs(document, 2))
    return paragraphs


def _add_spacer_paragraphs(document, count: int) -> list:
    paragraphs = []
    for _ in range(count):
        paragraph = document.add_paragraph()
        _set_paragraph_style(paragraph, "DCT-LetterheadSpacer")
        _set_paragraph_line_spacing(paragraph)
        paragraphs.append(paragraph)
    return paragraphs


def _add_number_paragraph(document, config: dict, settings: PageSettings):
    paragraph = document.add_paragraph()
    _set_paragraph_style(paragraph, "DCT-DocumentNumber")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run(_document_number(config))
    _set_run_font(run, "仿宋_GB2312", 16)
    _set_paragraph_line_spacing(paragraph)
    return paragraph


def _append_signers(
    paragraph,
    signers: list[dict],
    settings: PageSettings,
    *,
    single_at_first_slot: bool = False,
) -> None:
    text_width_cm = (
        settings.page_width_cm
        - settings.margin_left_cm
        - settings.margin_right_cm
    )
    right_blank_one_char = Cm(text_width_cm) - Pt(16)
    first_signer_position = right_blank_one_char - Cm(4.6)
    if len(signers) == 2:
        tab_positions = (first_signer_position, right_blank_one_char)
    elif single_at_first_slot:
        tab_positions = (first_signer_position,)
    else:
        tab_positions = (right_blank_one_char,)
    for position in tab_positions:
        paragraph.paragraph_format.tab_stops.add_tab_stop(position, WD_TAB_ALIGNMENT.RIGHT)
    for signer in signers:
        paragraph.add_run("\t")
        label = paragraph.add_run(f"{signer['label']}：")
        _set_run_font(label, "仿宋_GB2312", 16)
        name = paragraph.add_run(signer["name"])
        _set_run_font(name, "楷体_GB2312", 16)


def _add_number_and_signer_paragraphs(
    document,
    config: dict,
    settings: PageSettings,
) -> list:
    if config["document_direction"] != "upward" or not config["signers"]:
        return [_add_number_paragraph(document, config, settings)]

    paragraphs = []
    signers = config["signers"]
    signer_rows = [signers[offset:offset + 2] for offset in range(0, len(signers), 2)]
    for index, row_signers in enumerate(signer_rows):
        final_row = index == len(signer_rows) - 1
        paragraph = document.add_paragraph()
        _set_paragraph_style(
            paragraph,
            "DCT-DocumentNumber" if final_row else "DCT-SignerLine",
        )
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        if final_row:
            paragraph.paragraph_format.left_indent = Pt(16)
            number = paragraph.add_run(_document_number(config))
            _set_run_font(number, "仿宋_GB2312", 16)
        _append_signers(
            paragraph,
            row_signers,
            settings,
            single_at_first_slot=len(signers) > 1 and len(row_signers) == 1,
        )
        _set_paragraph_line_spacing(paragraph)
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
    _set_paragraph_line_spacing(paragraph, after_lines=2)
    # The 4 mm distance is a physical standard, not a whole-line gap.
    spacing = paragraph._p.get_or_add_pPr().get_or_add_spacing()
    spacing.set(qn("w:before"), str(round(Cm(0.4).twips)))
    spacing.attrib.pop(qn("w:beforeLines"), None)
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
        if style_id in {"DCT-LetterheadSpacer", "DCT-LetterheadMark"}:
            in_block = True
        if in_block and style_id in LETTERHEAD_STYLE_IDS:
            paragraph._element.getparent().remove(paragraph._element)
            removed += 1
            if style_id == "DCT-LetterheadSeparator":
                break
        elif in_block:
            break
    return removed


def remove_detected_letterhead(document, detection: LetterheadDetection) -> int:
    """Remove the body-flow block identified by *detection* from this document."""

    body_children = [
        child
        for child in document._body._element.iterchildren()
        if child.tag != qn("w:sectPr")
    ]
    removed = 0
    for index in sorted(set(detection.protected_body_indexes), reverse=True):
        if 0 <= index < len(body_children):
            element = body_children[index]
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
                removed += 1
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
    if detection.status != "none":
        remove_detected_letterhead(document, detection)
    resolved_settings = settings or PageSettings()
    ensure_letterhead_styles(document, rules, resolved_settings)
    paragraphs = _add_mark_paragraphs(document, normalized)
    paragraphs.extend(
        _add_number_and_signer_paragraphs(document, normalized, resolved_settings)
    )
    paragraphs.append(_add_separator(document, resolved_settings))
    elements = [paragraph._p for paragraph in paragraphs]
    _move_before(elements, _first_title_element(document))
    _set_managed_property(document)
    return LetterheadResult(
        "replaced" if detection.status != "none" else "generated",
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
    "remove_detected_letterhead",
    "remove_managed_letterhead",
]
