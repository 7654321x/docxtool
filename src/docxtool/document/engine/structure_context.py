"""Reconcile independent local-context candidates with document blocks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
from typing import Iterable

from docxtool.document.engine.context_candidate import (
    ContextCandidate,
    ContextEvidence,
    build_raw_element_facts,
    classify_context_candidate,
)
from docxtool.document.engine.document_structure import BlockKind, DocumentStructure, ElementKind


CONFIRMED_THRESHOLD = 0.85
PROVISIONAL_THRESHOLD = 0.60


class ValidationStatus(str, Enum):
    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ValidatedElement:
    index: int
    block_kind: BlockKind
    structure_kind: ElementKind
    context_kind: ElementKind
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
    ElementKind.HEADING_1, ElementKind.HEADING_2, ElementKind.HEADING_3, ElementKind.HEADING_4,
    ElementKind.BODY_PARAGRAPH, ElementKind.LIST, ElementKind.QUOTE, ElementKind.TABLE,
    ElementKind.FIGURE, ElementKind.CAPTION, ElementKind.UNKNOWN, ElementKind.PAGE_BREAK,
}
_ALLOWED_KINDS = {
    BlockKind.FRONT_MATTER: {
        ElementKind.LETTERHEAD_MARK, ElementKind.DOCUMENT_NUMBER, ElementKind.SIGNER,
        ElementKind.LETTERHEAD_SEPARATOR, ElementKind.PAGE_BREAK,
    },
    BlockKind.TITLE: {ElementKind.DOCUMENT_TITLE, ElementKind.TITLE_METADATA},
    BlockKind.BODY: _BODY_KINDS,
    BlockKind.ATTACHMENT_NOTE: {ElementKind.ATTACHMENT_NOTE_ITEM},
    BlockKind.SIGNATURE: {ElementKind.SIGNATURE_AGENCY, ElementKind.SIGNATURE_DATE, ElementKind.NOTE},
    BlockKind.ATTACHMENT_CONTENT: _BODY_KINDS | {ElementKind.ATTACHMENT_TITLE},
    BlockKind.UNKNOWN: {ElementKind.UNKNOWN, ElementKind.PAGE_BREAK},
}
_HEADING_LEVELS = {
    ElementKind.HEADING_1: 1, ElementKind.HEADING_2: 2,
    ElementKind.HEADING_3: 3, ElementKind.HEADING_4: 4,
}


def allowed_kinds_for_block(block_kind: BlockKind) -> frozenset[ElementKind]:
    return frozenset(_ALLOWED_KINDS[block_kind])


def validate_structure_context(structure: DocumentStructure, paragraphs: Iterable) -> ContextValidation:
    """Validate every structure element using independently rebuilt raw facts."""

    source = tuple(paragraphs)
    facts = build_raw_element_facts(source)
    if len(facts) != len(structure.elements):
        raise ValueError("raw fact stream does not align with document structure")
    block_map, confidence_map = _block_maps(structure)
    candidates = tuple(classify_context_candidate(facts, index) for index in range(len(facts)))
    results = []
    previous_heading = None

    for element, candidate in zip(structure.elements, candidates):
        block = block_map[element.index]
        block_confidence = confidence_map[element.index]
        evidence = [ContextEvidence("block", f"inside:{block.value}", block_confidence)]
        evidence.extend(candidate.evidence)
        status, final_kind, confidence = _reconcile(
            element.kind, candidate, block, block_confidence
        )
        if element.kind != candidate.kind and candidate.kind in _ALLOWED_KINDS[block]:
            evidence.append(ContextEvidence(
                "structural", "structure_context_kind_disagreement", -0.05
            ))
            if status == ValidationStatus.CONFIRMED:
                status = ValidationStatus.PROVISIONAL
                confidence = min(confidence, 0.84)

        level = _HEADING_LEVELS.get(candidate.kind)
        if level is not None:
            if previous_heading is not None and level > previous_heading + 1:
                evidence.append(ContextEvidence(
                    "structural", f"heading_level_jump_{previous_heading}_to_{level}", -0.05
                ))
            previous_heading = level

        fact = facts[element.index]
        results.append(ValidatedElement(
            element.index, block, element.kind, candidate.kind, final_kind, status,
            round(confidence, 3), tuple(evidence), candidate.original_type_id,
            candidate.text_fingerprint, candidate.style_fingerprint,
            _neighbor_fingerprint(facts, element.index), element.source_index, fact.node_identity,
        ))

    validation = ContextValidation(tuple(_structural_review(results)))
    validate_contextual_structure(structure, validation)
    return validation


def validate_contextual_structure(structure: DocumentStructure, validation: ContextValidation) -> None:
    """Assert ordering and semantic invariants after conservative review."""

    if len(validation.elements) != len(structure.elements):
        raise ValueError("not all structure elements have contextual results")
    if tuple(item.index for item in validation.elements) != tuple(range(len(structure.elements))):
        raise ValueError("contextual results changed original element order")
    for item in validation.elements:
        allowed = _ALLOWED_KINDS[item.block_kind]
        if item.status == ValidationStatus.CONFIRMED and item.context_kind not in allowed:
            raise ValueError("confirmed context kind is outside its block")
        if item.status == ValidationStatus.CONFLICT and item.final_kind != ElementKind.UNKNOWN:
            raise ValueError("conflicting element must remain unknown")
        required_block = {
            ElementKind.SIGNATURE_DATE: BlockKind.SIGNATURE,
            ElementKind.SIGNATURE_AGENCY: BlockKind.SIGNATURE,
            ElementKind.TITLE_METADATA: BlockKind.TITLE,
            ElementKind.ATTACHMENT_NOTE_ITEM: BlockKind.ATTACHMENT_NOTE,
            ElementKind.ATTACHMENT_TITLE: BlockKind.ATTACHMENT_CONTENT,
        }.get(item.final_kind)
        if required_block is not None and item.block_kind != required_block:
            raise ValueError(f"{item.final_kind.value} is outside {required_block.value}")


def revalidate_element(
    validated: ValidatedElement,
    structure: DocumentStructure,
    paragraphs: Iterable,
) -> bool:
    """Rebuild local facts and require the same still-safe context candidate."""

    source = tuple(paragraphs)
    facts = build_raw_element_facts(source)
    if not 0 <= validated.index < len(structure.elements) or len(facts) != len(structure.elements):
        return False
    block_map, _ = _block_maps(structure)
    if block_map.get(validated.index) != validated.block_kind:
        return False
    element = structure.elements[validated.index]
    fact = facts[validated.index]
    if element.source_index != validated.source_index:
        return False
    if fact.text_fingerprint != validated.text_fingerprint:
        return False
    if fact.style_fingerprint != validated.style_fingerprint:
        return False
    if fact.node_identity != validated.node_identity:
        return False
    if _neighbor_fingerprint(facts, validated.index) != validated.neighbor_fingerprint:
        return False
    candidate = classify_context_candidate(facts, validated.index)
    if candidate.kind != validated.context_kind:
        return False
    minimum = CONFIRMED_THRESHOLD if validated.status == ValidationStatus.CONFIRMED else PROVISIONAL_THRESHOLD
    return candidate.confidence >= minimum


def _reconcile(structure_kind, candidate: ContextCandidate, block, block_confidence):
    del structure_kind
    context_kind = candidate.kind
    context_confidence = candidate.confidence
    allowed = context_kind in _ALLOWED_KINDS[block]
    block_high = block_confidence >= CONFIRMED_THRESHOLD
    context_high = context_confidence >= CONFIRMED_THRESHOLD
    block_low = block_confidence < PROVISIONAL_THRESHOLD
    context_low = context_confidence < PROVISIONAL_THRESHOLD

    if allowed and block_high and context_high and context_kind != ElementKind.UNKNOWN:
        return ValidationStatus.CONFIRMED, context_kind, min(0.99, max(block_confidence, context_confidence) + 0.04)
    if not allowed and block_high and context_high:
        return ValidationStatus.CONFLICT, ElementKind.UNKNOWN, min(block_confidence, context_confidence)
    if block_low and context_low:
        return ValidationStatus.UNKNOWN, ElementKind.UNKNOWN, max(block_confidence, context_confidence)
    if allowed and context_confidence >= PROVISIONAL_THRESHOLD:
        return ValidationStatus.PROVISIONAL, context_kind, min(context_confidence, 0.84)
    if allowed and context_high:
        return ValidationStatus.PROVISIONAL, context_kind, min(context_confidence, 0.84)
    return ValidationStatus.PROVISIONAL, ElementKind.UNKNOWN, min(max(block_confidence, context_confidence), 0.84)


def _structural_review(results):
    reviewed = []
    for item in results:
        details = {evidence.detail for evidence in item.evidence}
        if item.status == ValidationStatus.CONFIRMED:
            required = None
            if item.final_kind == ElementKind.SIGNATURE_DATE:
                required = "previous:signature_candidate"
            elif item.final_kind == ElementKind.ATTACHMENT_TITLE:
                required = "preceded_by:real_page_boundary"
            elif item.final_kind == ElementKind.TITLE_METADATA:
                required = "title_like_before"
            if required and required not in details:
                item = replace(
                    item,
                    final_kind=ElementKind.UNKNOWN,
                    status=ValidationStatus.PROVISIONAL,
                    confidence=min(item.confidence, 0.59),
                    evidence=item.evidence + (
                        ContextEvidence("structural", f"missing_required:{required}", -0.25),
                    ),
                )
        reviewed.append(item)
    return reviewed


def _block_maps(structure):
    blocks, confidence = {}, {}
    spans = [span for span in (
        structure.front_matter, structure.title.span if structure.title else None,
        structure.body.span if structure.body else None, structure.attachment_note,
        structure.signature,
    ) if span]
    spans.extend(item.span for item in structure.attachments)
    spans.extend(structure.unknown)
    for span in spans:
        for index in range(span.start_index, span.end_index):
            blocks[index] = span.kind
            confidence[index] = span.confidence
    return blocks, confidence


def _neighbor_fingerprint(facts, index):
    values = []
    for neighbor in (index - 1, index + 1):
        if 0 <= neighbor < len(facts):
            fact = facts[neighbor]
            values.append(
                f"{fact.index}:{fact.source_index}:{fact.type_id}:"
                f"{fact.text_fingerprint}:{fact.style_fingerprint}:{fact.physical_kind}"
            )
        else:
            values.append("boundary")
    return sha256("|".join(values).encode("utf-8")).hexdigest()
