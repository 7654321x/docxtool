"""Read-only detection of existing first-page body-flow letterheads."""

from __future__ import annotations

from dataclasses import dataclass
import re

from lxml import etree
from docx.oxml.ns import qn

MANAGED_PROPERTY = "DocxtoolLetterheadVersion"
MANAGED_VERSION = "1"
LETTERHEAD_STYLE_IDS = (
    "DCT-LetterheadSpacer",
    "DCT-LetterheadMark",
    "DCT-DocumentNumber",
    "DCT-SignerLine",
    "DCT-LetterheadSeparator",
)
_STANDARD_DOCUMENT_NUMBER_RE = re.compile(
    r"^[^\s，。；：:（）()《》“”]{1,24}〔\d{4}〕\d+号(?:签发人[：:].{1,80})?$"
)
_STANDARD_DOCUMENT_NUMBER_CAPTURE_RE = re.compile(
    r"^(?P<agency_code>[^\s，。；：:（）()《》“”]{1,24})"
    r"〔(?P<year>\d{4})〕(?P<sequence>\d+)号"
    r"(?P<signer>签发人[：:].{1,80})?$"
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


@dataclass(frozen=True)
class LetterheadFields:
    mark_text: str = ""
    mark_display_mode: str = "agency_with_document"
    agency_code: str = ""
    year: int | None = None
    sequence: int | None = None
    signers: tuple[str, ...] = ()
    separator_style: str = "straight"
    issuance_mode: str = "single"


@dataclass(frozen=True)
class LetterheadDetection:
    status: str = "none"
    protected_body_indexes: tuple[int, ...] = ()
    details: tuple[str, ...] = ()
    fields: LetterheadFields | None = None


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


def _has_star_separator(element) -> bool:
    if "★" in _paragraph_text(element):
        return True
    return any(
        (
            node.tag.endswith("}prstGeom") and node.get("prst") == "star5"
        )
        or (
            node.tag.endswith("}group")
            and node.get("id") == "DocxToolLetterheadStarSeparator"
        )
        for node in element.iter()
    )


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
            and (
                _has_red_separator_border(child)
                or _has_star_separator(child)
            )
            and (
                not texts[index]
                or _is_document_number_line(texts[index])
                or _is_signer_line(texts[index])
            )
        )
    ]
    for signer_index in tuple(signer_indexes):
        following_separators = [index for index in separator_indexes if index > signer_index]
        # A missing separator is precisely the incomplete-header case we need
        # to repair. Continue recognizing bounded signer-name rows until a
        # separator or the first ordinary paragraph, so the new separator is
        # placed after the final signer instead of splitting that block.
        end_index = min(following_separators) if following_separators else len(top)
        for index in range(signer_index + 1, end_index):
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


def extract_letterhead_fields(
    document,
    detection: LetterheadDetection | None = None,
) -> LetterheadFields | None:
    """Extract reconstructable fields from one bounded recognized letterhead."""

    detection = detection or detect_letterhead(document)
    if detection.status not in {"managed", "recognized_external"}:
        return None
    body_children = [
        child
        for child in document._body._element.iterchildren()
        if child.tag != qn("w:sectPr")
    ]
    elements = [
        body_children[index]
        for index in detection.protected_body_indexes
        if 0 <= index < len(body_children) and body_children[index].tag == qn("w:p")
    ]
    mark_elements = [
        element
        for element in elements
        if _style_id(element) == "DCT-LetterheadMark"
        or _is_letterhead_mark(element, _paragraph_text(element))
        or _is_semantic_agency_file_mark(_paragraph_text(element))
        or _is_semantic_agency_name(_paragraph_text(element))
    ]
    mark_texts = [
        re.sub(r"\s+", "", _paragraph_text(element))
        for element in mark_elements
        if _paragraph_text(element).strip()
    ]
    if not mark_texts:
        return None
    mark_text = mark_texts[0]
    issuance_mode = "joint" if len(mark_texts) > 1 else "single"
    mark_display_mode = "agency_with_document" if mark_text.endswith("文件") else "agency_only"
    agency_name = mark_text[:-2] if mark_display_mode == "agency_with_document" else mark_text
    if not agency_name:
        return None

    number_match = None
    signer_values: list[str] = []
    for element in elements:
        compact = re.sub(r"\s+", "", _paragraph_text(element))
        if not compact:
            continue
        candidate = _STANDARD_DOCUMENT_NUMBER_CAPTURE_RE.fullmatch(compact)
        if candidate is not None:
            if number_match is not None:
                return None
            number_match = candidate
            inline_signer = candidate.group("signer") or ""
            if inline_signer:
                signer_values.append(re.split(r"[：:]", inline_signer, maxsplit=1)[1])
            continue
        if _SIGNER_LINE_RE.fullmatch(compact):
            signer_values.extend(
                value
                for value in re.split(r"签发人[：:]", compact)
                if value
            )
        elif signer_values and _looks_like_signer_continuation(compact):
            signer_values.append(compact)
    if number_match is None:
        return None
    signers = tuple(value for value in signer_values if value)
    return LetterheadFields(
        mark_text=mark_text,
        mark_display_mode=mark_display_mode,
        agency_code=number_match.group("agency_code"),
        year=int(number_match.group("year")),
        sequence=int(number_match.group("sequence")),
        signers=signers,
        separator_style=(
            "star" if any(_has_star_separator(element) for element in elements) else "straight"
        ),
        issuance_mode=issuance_mode,
    )


def with_letterhead_fields(
    document,
    detection: LetterheadDetection | None = None,
) -> LetterheadDetection:
    """Attach reconstructable source fields without changing detection status."""

    detection = detection or detect_letterhead(document)
    if detection.fields is not None:
        return detection
    fields = extract_letterhead_fields(document, detection)
    if fields is None:
        return detection
    return LetterheadDetection(
        detection.status,
        detection.protected_body_indexes,
        detection.details,
        fields,
    )

__all__ = [
    "LETTERHEAD_STYLE_IDS",
    "LetterheadDetection",
    "LetterheadFields",
    "MANAGED_PROPERTY",
    "MANAGED_VERSION",
    "detect_letterhead",
    "extract_letterhead_fields",
    "with_letterhead_fields",
]
