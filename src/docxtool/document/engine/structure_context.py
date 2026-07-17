"""Read-only reconciliation of document blocks and importer context results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Iterable

from docxtool.document.engine.document_structure import (
    BlockKind,
    DocumentStructure,
    ElementKind,
)


CONFIRMED_THRESHOLD = 0.85
PROVISIONAL_THRESHOLD = 0.60


class ValidationStatus(str, Enum):
    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ContextEvidence:
    source: str
    detail: str
    weight: float


@dataclass(frozen=True)
class ValidatedElement:
    index: int
    block_kind: BlockKind
    proposed_kind: ElementKind
    final_kind: ElementKind
    status: ValidationStatus
    confidence: float
    evidence: tuple[ContextEvidence, ...]
    original_type_id: str | None
    text_fingerprint: str
    style_fingerprint: str
    neighbor_fingerprint: str
    source_index: int | None
    node_identity: int | None


@dataclass(frozen=True)
class ContextValidation:
    elements: tuple[ValidatedElement, ...]


_BODY_KINDS = {
    ElementKind.HEADING_1,
    ElementKind.HEADING_2,
    ElementKind.HEADING_3,
    ElementKind.HEADING_4,
    ElementKind.BODY_PARAGRAPH,
    ElementKind.LIST,
    ElementKind.QUOTE,
    ElementKind.TABLE,
    ElementKind.FIGURE,
    ElementKind.CAPTION,
    ElementKind.UNKNOWN,
    ElementKind.PAGE_BREAK,
}
_ALLOWED_KINDS = {
    BlockKind.FRONT_MATTER: {
        ElementKind.LETTERHEAD_MARK,
        ElementKind.DOCUMENT_NUMBER,
        ElementKind.SIGNER,
        ElementKind.LETTERHEAD_SEPARATOR,
        ElementKind.PAGE_BREAK,
    },
    BlockKind.TITLE: {ElementKind.DOCUMENT_TITLE, ElementKind.TITLE_METADATA},
    BlockKind.BODY: _BODY_KINDS,
    BlockKind.ATTACHMENT_NOTE: {ElementKind.ATTACHMENT_NOTE_ITEM},
    BlockKind.SIGNATURE: {
        ElementKind.SIGNATURE_AGENCY,
        ElementKind.SIGNATURE_DATE,
        ElementKind.NOTE,
    },
    BlockKind.ATTACHMENT_CONTENT: _BODY_KINDS | {ElementKind.ATTACHMENT_TITLE},
    BlockKind.UNKNOWN: {ElementKind.UNKNOWN, ElementKind.PAGE_BREAK},
}
_HEADING_LEVELS = {
    ElementKind.HEADING_1: 1,
    ElementKind.HEADING_2: 2,
    ElementKind.HEADING_3: 3,
    ElementKind.HEADING_4: 4,
}


def validate_structure_context(
    structure: DocumentStructure,
    paragraphs: Iterable,
) -> ContextValidation:
    """Reconcile block candidates with existing importer classifications."""

    source = tuple(paragraphs)
    block_map, block_confidence = _block_maps(structure)
    results: list[ValidatedElement] = []
    previous_heading: int | None = None

    for element in structure.elements:
        block_kind = block_map[element.index]
        paragraph = _source_paragraph(source, element.source_index)
        context_confidence = _context_confidence(element.confidence, paragraph)
        current_block_confidence = block_confidence[element.index]
        allowed = element.kind in _ALLOWED_KINDS[block_kind]
        evidence = [
            ContextEvidence("block", f"inside:{block_kind.value}", current_block_confidence),
            ContextEvidence("context", f"type:{_type_id(paragraph) or 'virtual'}", context_confidence),
        ]
        evidence.extend(_role_evidence(element.kind, block_kind, structure, element.index))
        evidence.append(ContextEvidence("style", f"fingerprint:{_style_fingerprint(paragraph)[:12]}", 0.05))
        evidence.append(ContextEvidence("text", f"fingerprint:{_text_fingerprint(element.text)[:12]}", 0.05))

        level = _HEADING_LEVELS.get(element.kind)
        if level is not None:
            if previous_heading is not None and level > previous_heading + 1:
                evidence.append(
                    ContextEvidence(
                        "structural",
                        f"heading_level_jump_{previous_heading}_to_{level}",
                        -0.05,
                    )
                )
            previous_heading = level

        status, final_kind, confidence = _reconcile(
            element.kind,
            allowed,
            current_block_confidence,
            context_confidence,
        )
        results.append(
            ValidatedElement(
                index=element.index,
                block_kind=block_kind,
                proposed_kind=element.kind,
                final_kind=final_kind,
                status=status,
                confidence=confidence,
                evidence=tuple(evidence),
                original_type_id=_type_id(paragraph),
                text_fingerprint=_text_fingerprint(element.text),
                style_fingerprint=_style_fingerprint(paragraph),
                neighbor_fingerprint=_neighbor_fingerprint(structure, element.index, source),
                source_index=element.source_index,
                node_identity=_node_identity(paragraph),
            )
        )

    validation = ContextValidation(tuple(results))
    validate_contextual_structure(structure, validation)
    return validation


def validate_contextual_structure(
    structure: DocumentStructure,
    validation: ContextValidation,
) -> None:
    """Check contextual results without changing the imported document."""

    if len(validation.elements) != len(structure.elements):
        raise ValueError("not all structure elements have contextual results")
    if tuple(item.index for item in validation.elements) != tuple(range(len(structure.elements))):
        raise ValueError("contextual results changed original element order")
    seen: set[int] = set()
    for item in validation.elements:
        if item.index in seen:
            raise ValueError("an element has more than one contextual result")
        seen.add(item.index)
        if item.status == ValidationStatus.CONFIRMED and item.final_kind not in _ALLOWED_KINDS[item.block_kind]:
            raise ValueError("confirmed element is outside its allowed block")
        if item.status == ValidationStatus.CONFLICT and item.final_kind != ElementKind.UNKNOWN:
            raise ValueError("conflicting element must remain unknown")
        if item.final_kind == ElementKind.SIGNATURE_DATE and item.block_kind != BlockKind.SIGNATURE:
            raise ValueError("signature date is outside signature block")
        if item.final_kind == ElementKind.TITLE_METADATA and item.block_kind != BlockKind.TITLE:
            raise ValueError("title metadata is outside title block")
        if item.final_kind == ElementKind.ATTACHMENT_TITLE and item.block_kind != BlockKind.ATTACHMENT_CONTENT:
            raise ValueError("attachment title is outside attachment content")
        if item.final_kind == ElementKind.ATTACHMENT_NOTE_ITEM and item.block_kind == BlockKind.ATTACHMENT_CONTENT:
            raise ValueError("attachment note item is inside attachment content")


def revalidate_element(
    validated: ValidatedElement,
    structure: DocumentStructure,
    paragraphs: Iterable,
) -> bool:
    """Return whether a previously validated element still matches current state."""

    source = tuple(paragraphs)
    if not 0 <= validated.index < len(structure.elements):
        return False
    element = structure.elements[validated.index]
    block_map, _ = _block_maps(structure)
    if block_map.get(validated.index) != validated.block_kind:
        return False
    if element.source_index != validated.source_index:
        return False
    paragraph = _source_paragraph(source, validated.source_index)
    current_text = _current_text(element, paragraph)
    if _text_fingerprint(current_text) != validated.text_fingerprint:
        return False
    if _style_fingerprint(paragraph) != validated.style_fingerprint:
        return False
    if _neighbor_fingerprint(structure, validated.index, source) != validated.neighbor_fingerprint:
        return False
    current_identity = _node_identity(paragraph)
    return validated.node_identity is None or current_identity == validated.node_identity


def _reconcile(proposed, allowed, block_confidence, context_confidence):
    block_high = block_confidence >= CONFIRMED_THRESHOLD
    context_high = context_confidence >= CONFIRMED_THRESHOLD
    block_low = block_confidence < PROVISIONAL_THRESHOLD
    context_low = context_confidence < PROVISIONAL_THRESHOLD

    if allowed and block_high and context_high and proposed != ElementKind.UNKNOWN:
        return ValidationStatus.CONFIRMED, proposed, round(min(0.99, max(block_confidence, context_confidence) + 0.04), 3)
    if not allowed and block_high and context_high:
        return ValidationStatus.CONFLICT, ElementKind.UNKNOWN, round(min(block_confidence, context_confidence), 3)
    if block_low and context_low:
        return ValidationStatus.UNKNOWN, ElementKind.UNKNOWN, round(max(block_confidence, context_confidence), 3)
    if allowed and context_high:
        return ValidationStatus.PROVISIONAL, proposed, round(min(context_confidence, 0.84), 3)
    if allowed and not context_low:
        return ValidationStatus.PROVISIONAL, proposed, round(min(max(block_confidence, context_confidence), 0.84), 3)
    return ValidationStatus.PROVISIONAL, ElementKind.UNKNOWN, round(min(max(block_confidence, context_confidence), 0.84), 3)


def _role_evidence(kind, block, structure, index):
    result = []
    if kind == ElementKind.TITLE_METADATA and block == BlockKind.TITLE:
        result.append(ContextEvidence("context", "after:document_title", 0.20))
        result.append(ContextEvidence("context", "before:first_body_element", 0.15))
    elif kind == ElementKind.SIGNATURE_DATE and block == BlockKind.SIGNATURE:
        result.append(ContextEvidence("context", "paired:signature_agency", 0.25))
        result.append(ContextEvidence("structural", "position:main_document_tail", 0.15))
    elif kind == ElementKind.SIGNATURE_AGENCY and block == BlockKind.SIGNATURE:
        result.append(ContextEvidence("context", "before:signature_date", 0.25))
    elif kind == ElementKind.ATTACHMENT_NOTE_ITEM and block == BlockKind.ATTACHMENT_NOTE:
        result.append(ContextEvidence("structural", "before:signature_or_attachment_content", 0.20))
    elif kind == ElementKind.ATTACHMENT_TITLE and block == BlockKind.ATTACHMENT_CONTENT:
        previous = structure.elements[index - 1].kind if index else None
        if previous == ElementKind.PAGE_BREAK:
            result.append(ContextEvidence("structural", "after:real_page_boundary", 0.25))
    elif kind == ElementKind.BODY_PARAGRAPH and block == BlockKind.BODY:
        result.append(ContextEvidence("context", "inside:main_body_bounds", 0.15))
    return result


def _block_maps(structure):
    blocks = {}
    confidence = {}
    spans = []
    for span in (
        structure.front_matter,
        structure.title.span if structure.title else None,
        structure.body.span if structure.body else None,
        structure.attachment_note,
        structure.signature,
    ):
        if span:
            spans.append(span)
    spans.extend(item.span for item in structure.attachments)
    spans.extend(structure.unknown)
    for span in spans:
        for index in range(span.start_index, span.end_index):
            blocks[index] = span.kind
            confidence[index] = span.confidence
    return blocks, confidence


def _context_confidence(default, paragraph):
    if paragraph is None:
        return default
    value = (getattr(paragraph, "meta", {}) or {}).get("classification_confidence", default)
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _source_paragraph(paragraphs, source_index):
    if source_index is None or not 0 <= source_index < len(paragraphs):
        return None
    return paragraphs[source_index]


def _type_id(paragraph):
    return str(getattr(paragraph, "type_id", "") or "") or None


def _current_text(element, paragraph):
    if paragraph is None:
        return element.text
    return str(getattr(paragraph, "original_text", "") or getattr(paragraph, "text", "") or "").strip()


def _text_fingerprint(text):
    return sha256(str(text or "").strip().encode("utf-8")).hexdigest()


def _style_fingerprint(paragraph):
    if paragraph is None:
        value = "virtual"
    else:
        features = getattr(paragraph, "features", None)
        meta = getattr(paragraph, "meta", {}) or {}
        value = "|".join((
            str(getattr(features, "style_name", "") or ""),
            str(getattr(features, "alignment", "") or ""),
            str(getattr(paragraph, "type_id", "") or ""),
            "page" if any(getattr(token, "kind", "") == "page_break" for token in getattr(paragraph, "inline_tokens", ())) else "",
            "section" if meta.get("sectPr") is not None else "",
        ))
    return sha256(value.encode("utf-8")).hexdigest()


def _neighbor_fingerprint(structure, index, paragraphs):
    values = []
    for neighbor in (index - 1, index + 1):
        if 0 <= neighbor < len(structure.elements):
            item = structure.elements[neighbor]
            paragraph = _source_paragraph(paragraphs, item.source_index)
            values.append(
                f"{item.index}:{item.kind.value}:{item.source_index}:"
                f"{_text_fingerprint(_current_text(item, paragraph))}:"
                f"{_style_fingerprint(paragraph)}"
            )
        else:
            values.append("boundary")
    return sha256("|".join(values).encode("utf-8")).hexdigest()


def _node_identity(paragraph):
    if paragraph is None:
        return None
    holder = (getattr(paragraph, "meta", {}) or {}).get("paragraph_xml")
    node = getattr(holder, "_p", None)
    if node is None:
        node = getattr(holder, "_element", None)
    return id(node) if node is not None else None
