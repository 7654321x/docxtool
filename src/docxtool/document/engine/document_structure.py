"""Read-only structural model for an imported official document.

The analyzer consumes the existing importer result.  It never mutates document
objects, paragraph data, or OOXML nodes, and it is intentionally not wired into
the rendering pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

from docx.oxml.ns import qn


CONFIRMED_CONFIDENCE = 0.85
_ATTACHMENT_TITLE_RE = re.compile(r"^附件\s*(?:[:：]\s*)?([0-9一二三四五六七八九十]*)\s*[:：]?$" )


class BlockKind(str, Enum):
    FRONT_MATTER = "front_matter"
    TITLE = "title"
    BODY = "body"
    ATTACHMENT_NOTE = "attachment_note"
    SIGNATURE = "signature"
    ATTACHMENT_CONTENT = "attachment_content"
    UNKNOWN = "unknown"


class ElementKind(str, Enum):
    LETTERHEAD_MARK = "letterhead_mark"
    DOCUMENT_NUMBER = "document_number"
    SIGNER = "signer"
    LETTERHEAD_SEPARATOR = "letterhead_separator"
    DOCUMENT_TITLE = "document_title"
    TITLE_METADATA = "title_metadata"
    HEADING_1 = "heading_1"
    HEADING_2 = "heading_2"
    HEADING_3 = "heading_3"
    HEADING_4 = "heading_4"
    BODY_PARAGRAPH = "body_paragraph"
    LIST = "list"
    QUOTE = "quote"
    TABLE = "table"
    FIGURE = "figure"
    CAPTION = "caption"
    ATTACHMENT_NOTE_ITEM = "attachment_note_item"
    SIGNATURE_AGENCY = "signature_agency"
    SIGNATURE_DATE = "signature_date"
    NOTE = "note"
    ATTACHMENT_TITLE = "attachment_title"
    PAGE_BREAK = "page_break"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ElementRef:
    index: int
    kind: ElementKind
    confidence: float
    evidence: tuple[str, ...]
    source_index: int | None = None


@dataclass(frozen=True)
class BlockSpan:
    kind: BlockKind
    start_index: int
    end_index: int
    elements: tuple[ElementRef, ...]
    confidence: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class TitleBlock:
    span: BlockSpan
    title_elements: tuple[ElementRef, ...]
    metadata_elements: tuple[ElementRef, ...]


@dataclass(frozen=True)
class BodyBlock:
    span: BlockSpan
    elements: tuple[ElementRef, ...]


@dataclass(frozen=True)
class AttachmentBlock:
    ordinal: int
    span: BlockSpan
    title_elements: tuple[ElementRef, ...]
    content_elements: tuple[ElementRef, ...]
    starts_after_page_break: bool


@dataclass(frozen=True)
class BoundaryRule:
    before: BlockKind
    after: BlockKind
    spacing_lines: int = 0
    page_break: bool = False


BOUNDARY_RULES = (
    BoundaryRule(BlockKind.FRONT_MATTER, BlockKind.TITLE, spacing_lines=2),
    BoundaryRule(BlockKind.TITLE, BlockKind.BODY, spacing_lines=1),
    BoundaryRule(BlockKind.BODY, BlockKind.ATTACHMENT_NOTE, spacing_lines=1),
    BoundaryRule(BlockKind.ATTACHMENT_NOTE, BlockKind.SIGNATURE, spacing_lines=3),
    BoundaryRule(BlockKind.BODY, BlockKind.SIGNATURE, spacing_lines=3),
    BoundaryRule(BlockKind.SIGNATURE, BlockKind.ATTACHMENT_CONTENT, page_break=True),
    BoundaryRule(BlockKind.ATTACHMENT_CONTENT, BlockKind.ATTACHMENT_CONTENT, page_break=True),
)


@dataclass(frozen=True)
class DocumentStructure:
    front_matter: BlockSpan | None
    title: TitleBlock | None
    body: BodyBlock | None
    attachment_note: BlockSpan | None
    signature: BlockSpan | None
    attachments: tuple[AttachmentBlock, ...]
    unknown: tuple[BlockSpan, ...]
    elements: tuple[ElementRef, ...]
    boundary_rules: tuple[BoundaryRule, ...] = BOUNDARY_RULES


_STYLE_KINDS = {
    "DCT-LetterheadMark": ElementKind.LETTERHEAD_MARK,
    "DCT-DocumentNumber": ElementKind.DOCUMENT_NUMBER,
    "DCT-SignerLine": ElementKind.SIGNER,
    "DCT-LetterheadSeparator": ElementKind.LETTERHEAD_SEPARATOR,
}
_TYPE_KINDS = {
    "title": ElementKind.DOCUMENT_TITLE,
    "title_cont": ElementKind.DOCUMENT_TITLE,
    "heading1": ElementKind.HEADING_1,
    "heading1_report": ElementKind.HEADING_1,
    "heading2": ElementKind.HEADING_2,
    "heading3": ElementKind.HEADING_3,
    "heading4": ElementKind.HEADING_4,
    "body": ElementKind.BODY_PARAGRAPH,
    "attachment_body": ElementKind.BODY_PARAGRAPH,
    "addressing": ElementKind.BODY_PARAGRAPH,
    "responsibility_line": ElementKind.BODY_PARAGRAPH,
    "list": ElementKind.LIST,
    "list_item": ElementKind.LIST,
    "quote": ElementKind.QUOTE,
    "attachment_note": ElementKind.ATTACHMENT_NOTE_ITEM,
    "attachment_note_item": ElementKind.ATTACHMENT_NOTE_ITEM,
    "sign_org": ElementKind.SIGNATURE_AGENCY,
    "sign_date": ElementKind.SIGNATURE_DATE,
    "note": ElementKind.NOTE,
    "annotation": ElementKind.NOTE,
    "attachment_page_mark": ElementKind.ATTACHMENT_TITLE,
    "attachment_title": ElementKind.ATTACHMENT_TITLE,
    "__table__": ElementKind.TABLE,
    "__image__": ElementKind.FIGURE,
    "__object_caption__": ElementKind.CAPTION,
}
_TITLE_METADATA_TYPES = {"author_line", "role_name", "date_line", "title2", "meeting_line", "location_line"}


def analyze_document_structure(document_data) -> DocumentStructure:
    """Build a deterministic, read-only structure from ``DocumentData``."""

    elements = _collect_elements(document_data.paragraphs)
    labels = [BlockKind.UNKNOWN for _ in elements]

    front_range = _front_matter_range(elements)
    if front_range:
        _label(labels, *front_range, BlockKind.FRONT_MATTER)

    attachment_starts = _attachment_starts(elements)
    first_attachment = attachment_starts[0] if attachment_starts else len(elements)
    signature_range = _signature_range(elements, first_attachment)
    note_range = _attachment_note_range(elements, signature_range, first_attachment)
    title_range = _title_range(elements, front_range, note_range, signature_range, first_attachment)

    if title_range:
        _label(labels, *title_range, BlockKind.TITLE)
    if note_range:
        _label(labels, *note_range, BlockKind.ATTACHMENT_NOTE)
    if signature_range:
        _label(labels, *signature_range, BlockKind.SIGNATURE)

    attachments = _label_attachments(elements, labels, attachment_starts)
    body_start = title_range[1] if title_range else (front_range[1] if front_range else 0)
    body_end = min(
        [value[0] for value in (note_range, signature_range) if value] + [first_attachment]
    )
    body_indexes = [
        index for index in range(body_start, body_end)
        if labels[index] == BlockKind.UNKNOWN and elements[index].kind != ElementKind.PAGE_BREAK
    ]
    if body_indexes:
        _label(labels, min(body_indexes), max(body_indexes) + 1, BlockKind.BODY, only_unknown=True)
        for index in range(min(body_indexes), max(body_indexes) + 1):
            if labels[index] == BlockKind.UNKNOWN and elements[index].kind == ElementKind.PAGE_BREAK:
                labels[index] = BlockKind.BODY

    spans = _spans(elements, labels)
    front = _single_span(spans, BlockKind.FRONT_MATTER)
    title_span = _single_span(spans, BlockKind.TITLE)
    body_span = _single_span(spans, BlockKind.BODY)
    note_span = _single_span(spans, BlockKind.ATTACHMENT_NOTE)
    signature = _single_span(spans, BlockKind.SIGNATURE)
    title = None
    if title_span:
        title = TitleBlock(
            title_span,
            tuple(item for item in title_span.elements if item.kind == ElementKind.DOCUMENT_TITLE),
            tuple(item for item in title_span.elements if item.kind == ElementKind.TITLE_METADATA),
        )
    structure = DocumentStructure(
        front,
        title,
        BodyBlock(body_span, body_span.elements) if body_span else None,
        note_span,
        signature,
        tuple(attachments),
        tuple(span for span in spans if span.kind == BlockKind.UNKNOWN),
        elements,
    )
    validate_document_structure(structure, len(elements))
    return structure


def validate_document_structure(structure: DocumentStructure, element_count: int) -> None:
    """Validate ordering, coverage, and non-overlap of top-level spans."""

    spans = _all_spans(structure)
    previous_end = 0
    covered: list[int] = []
    for span in sorted(spans, key=lambda item: item.start_index):
        if not 0 <= span.start_index < span.end_index <= element_count:
            raise ValueError(f"invalid document structure span: {span}")
        if span.start_index < previous_end:
            raise ValueError(f"overlapping document structure span: {span}")
        if tuple(item.index for item in span.elements) != tuple(range(span.start_index, span.end_index)):
            raise ValueError(f"non-contiguous document structure span: {span}")
        covered.extend(range(span.start_index, span.end_index))
        previous_end = span.end_index
    if sorted(covered) != list(range(element_count)):
        raise ValueError("document structure does not account for every element")


def _collect_elements(paragraphs: Iterable) -> tuple[ElementRef, ...]:
    pending: list[tuple[ElementKind, float, tuple[str, ...], int | None]] = []
    for source_index, paragraph in enumerate(paragraphs):
        if _has_page_break_before(paragraph):
            pending.append((ElementKind.PAGE_BREAK, 0.98, ("ooxml:pageBreakBefore",), source_index))
        elif _has_inline_page_break(paragraph):
            pending.append((ElementKind.PAGE_BREAK, 0.98, ("inline:w:br-page",), source_index))
        pending.append(_classify_element(paragraph, source_index))
        if _has_section_break(paragraph):
            pending.append((ElementKind.PAGE_BREAK, 0.95, ("ooxml:sectPr",), source_index))
    return tuple(
        ElementRef(index, kind, confidence, evidence, source_index)
        for index, (kind, confidence, evidence, source_index) in enumerate(pending)
    )


def _classify_element(paragraph, source_index: int):
    type_id = str(getattr(paragraph, "type_id", "") or "")
    style_id = _paragraph_style_id(paragraph)
    if type_id == "__letterhead__":
        kind = _STYLE_KINDS.get(style_id, ElementKind.UNKNOWN)
        confidence = 0.99 if kind != ElementKind.UNKNOWN else 0.45
        return kind, confidence, ("type:__letterhead__", f"style:{style_id or 'unknown'}"), source_index
    if type_id in _TITLE_METADATA_TYPES:
        return ElementKind.TITLE_METADATA, 0.9, (f"type:{type_id}", "position:title-area"), source_index
    kind = _TYPE_KINDS.get(type_id, ElementKind.UNKNOWN)
    confidence = 0.95 if kind != ElementKind.UNKNOWN else 0.4
    evidence = (f"type:{type_id or 'unknown'}",)
    return kind, confidence, evidence, source_index


def _paragraph_style_id(paragraph) -> str:
    meta = getattr(paragraph, "meta", {}) or {}
    xml_holder = meta.get("paragraph_xml")
    element = _xml_element(xml_holder)
    if element is None:
        return ""
    style = element.find("./" + qn("w:pPr") + "/" + qn("w:pStyle"))
    return style.get(qn("w:val"), "") if style is not None else ""


def _has_inline_page_break(paragraph) -> bool:
    return any(getattr(token, "kind", "") == "page_break" for token in getattr(paragraph, "inline_tokens", ()))


def _has_page_break_before(paragraph) -> bool:
    meta = getattr(paragraph, "meta", {}) or {}
    if meta.get("page_break_before"):
        return True
    xml_holder = meta.get("paragraph_xml")
    element = _xml_element(xml_holder)
    return element is not None and element.find("./" + qn("w:pPr") + "/" + qn("w:pageBreakBefore")) is not None


def _xml_element(holder):
    element = getattr(holder, "_p", None)
    return element if element is not None else getattr(holder, "_element", None)


def _has_section_break(paragraph) -> bool:
    return (getattr(paragraph, "meta", {}) or {}).get("sectPr") is not None


def _front_matter_range(elements):
    allowed = {
        ElementKind.LETTERHEAD_MARK,
        ElementKind.DOCUMENT_NUMBER,
        ElementKind.SIGNER,
        ElementKind.LETTERHEAD_SEPARATOR,
    }
    indexes = [item.index for item in elements if item.kind in allowed]
    if not indexes or indexes[0] > 4:
        return None
    separator = next((index for index in indexes if elements[index].kind == ElementKind.LETTERHEAD_SEPARATOR), None)
    if separator is None:
        return None
    start = indexes[0]
    if any(elements[index].kind not in allowed for index in range(start, separator + 1)):
        return None
    return start, separator + 1


def _title_range(elements, front_range, note_range, signature_range, first_attachment):
    start_at = front_range[1] if front_range else 0
    limit = min([value[0] for value in (note_range, signature_range) if value] + [first_attachment])
    title_indexes = [
        index for index in range(start_at, limit)
        if elements[index].kind == ElementKind.DOCUMENT_TITLE
    ]
    if not title_indexes:
        return None
    start, end = min(title_indexes), max(title_indexes) + 1
    while end < limit and elements[end].kind == ElementKind.TITLE_METADATA:
        end += 1
    return start, end


def _signature_range(elements, limit):
    for index in range(limit - 2, -1, -1):
        if elements[index].kind != ElementKind.SIGNATURE_AGENCY:
            continue
        cursor = index + 1
        while cursor < limit and elements[cursor].kind == ElementKind.NOTE:
            cursor += 1
        if cursor < limit and elements[cursor].kind == ElementKind.SIGNATURE_DATE:
            end = cursor + 1
            while end < limit and elements[end].kind == ElementKind.NOTE:
                end += 1
            return index, end
    return None


def _attachment_note_range(elements, signature_range, first_attachment):
    limit = signature_range[0] if signature_range else first_attachment
    indexes = [
        index for index in range(limit)
        if elements[index].kind == ElementKind.ATTACHMENT_NOTE_ITEM
    ]
    if not indexes:
        return None
    start = indexes[-1]
    while start > 0 and elements[start - 1].kind == ElementKind.ATTACHMENT_NOTE_ITEM:
        start -= 1
    end = indexes[-1] + 1
    if any(elements[index].kind != ElementKind.ATTACHMENT_NOTE_ITEM for index in range(start, end)):
        return None
    return start, end


def _attachment_starts(elements):
    starts = []
    for index, item in enumerate(elements):
        if item.kind != ElementKind.ATTACHMENT_TITLE:
            continue
        previous = index - 1
        if previous >= 0 and elements[previous].kind == ElementKind.PAGE_BREAK:
            starts.append(previous)
    return starts


def _label_attachments(elements, labels, starts):
    result = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(elements)
        _label(labels, start, end, BlockKind.ATTACHMENT_CONTENT)
        span = _make_span(BlockKind.ATTACHMENT_CONTENT, elements, start, end)
        titles = tuple(item for item in span.elements if item.kind == ElementKind.ATTACHMENT_TITLE)
        ordinal = _attachment_ordinal(titles[0], position + 1) if titles else position + 1
        result.append(
            AttachmentBlock(
                ordinal,
                span,
                titles,
                tuple(item for item in span.elements if item.kind not in {ElementKind.PAGE_BREAK, ElementKind.ATTACHMENT_TITLE}),
                True,
            )
        )
    return result


def _attachment_ordinal(element, fallback):
    del element
    return fallback


def _label(labels, start, end, kind, *, only_unknown=False):
    for index in range(start, end):
        if not only_unknown or labels[index] == BlockKind.UNKNOWN:
            labels[index] = kind


def _spans(elements, labels):
    if not elements:
        return []
    spans = []
    start = 0
    for index in range(1, len(elements) + 1):
        if index == len(elements) or labels[index] != labels[start]:
            spans.append(_make_span(labels[start], elements, start, index))
            start = index
    return spans


def _make_span(kind, elements, start, end):
    items = tuple(elements[start:end])
    confidence = min((item.confidence for item in items), default=0.0)
    evidence = tuple(dict.fromkeys(value for item in items for value in item.evidence))
    return BlockSpan(kind, start, end, items, confidence, evidence)


def _single_span(spans, kind):
    matches = [span for span in spans if span.kind == kind]
    if len(matches) > 1:
        raise ValueError(f"non-contiguous {kind.value} block")
    return matches[0] if matches else None


def _all_spans(structure):
    spans = []
    for value in (structure.front_matter, structure.title.span if structure.title else None,
                  structure.body.span if structure.body else None, structure.attachment_note,
                  structure.signature):
        if value:
            spans.append(value)
    spans.extend(item.span for item in structure.attachments)
    spans.extend(structure.unknown)
    return spans
