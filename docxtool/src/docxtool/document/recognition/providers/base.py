"""Shared candidate models and provider helper functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..features import DocumentBlock, ParagraphFeatures
from ..global_context import DocumentContext
from ..model import DocumentMode, ParagraphType, SectionKind


_STRUCTURE_CONTEXT_TYPES = {
    ParagraphType.ATTACHMENT_NOTE,
    ParagraphType.ATTACHMENT_NOTE_ITEM,
    ParagraphType.SIGNATURE_DATE,
    ParagraphType.SIGNATURE_ORG,
}


@dataclass(frozen=True)
class Candidate:
    paragraph_type: ParagraphType
    score: float
    source: str
    evidence: tuple[str, ...] = ()
    vetoes: frozenset[ParagraphType] = frozenset()
    hard: bool = False
    section_hint: SectionKind | None = None
    heading_level: int | None = None


class CandidateContext(Protocol):
    mode: DocumentMode
    previous_type: ParagraphType | None
    index: int
    boundary_before: bool
    document_context: DocumentContext


class CandidateProvider(Protocol):
    name: str

    def propose(
        self,
        block: DocumentBlock,
        features: ParagraphFeatures,
        context: CandidateContext,
    ) -> list[Candidate]: ...


def _section_hint_for_type(paragraph_type: ParagraphType) -> SectionKind:
    if paragraph_type in {ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION}:
        return SectionKind.HEADER
    if paragraph_type == ParagraphType.DISPATCH_NUMBER:
        return SectionKind.DISPATCH_META
    if paragraph_type in {ParagraphType.RECIPIENT, ParagraphType.ADDRESSING}:
        return SectionKind.RECIPIENT
    if paragraph_type in {ParagraphType.SIGNATURE_ORG, ParagraphType.SIGNATURE_DATE}:
        return SectionKind.SIGNATURE
    if paragraph_type in {ParagraphType.ATTACHMENT_NOTE, ParagraphType.ATTACHMENT_NOTE_ITEM}:
        return SectionKind.ATTACHMENT_NOTE
    if paragraph_type in {
        ParagraphType.ATTACHMENT_TITLE,
        ParagraphType.ATTACHMENT_BODY,
        ParagraphType.ATTACHMENT_PAGE_MARK,
    }:
        return SectionKind.ATTACHMENT_BODY
    return SectionKind.BODY


def _body_like_candidate(features: ParagraphFeatures) -> bool:
    if not features.compact_text:
        return False
    if features.dispatch_number_match or features.date_match or features.heading_shape_level:
        return False
    return bool(
        (features.ends_with_sentence_punctuation and features.text_length >= 12)
        or features.text_length >= 34
    )


def _context_evidence_for(
    paragraph_type: ParagraphType,
    features: ParagraphFeatures,
    context: CandidateContext,
) -> tuple[str, ...]:
    document_context = context.document_context
    if document_context is None:
        return ()
    if paragraph_type == ParagraphType.ATTACHMENT_NOTE:
        return document_context.attachment_note_reasons(context.index)
    if paragraph_type == ParagraphType.ATTACHMENT_NOTE_ITEM:
        return document_context.attachment_item_reasons(context.index)
    if paragraph_type == ParagraphType.SIGNATURE_ORG:
        return document_context.signature_org_reasons(context.index)
    if paragraph_type == ParagraphType.SIGNATURE_DATE:
        return document_context.signature_date_reasons(context.index)
    return ()


def _soften_unverified_structure(
    paragraph_type: ParagraphType,
    score: float,
    evidence: str,
    features: ParagraphFeatures,
    context: CandidateContext,
) -> tuple[float, str]:
    if paragraph_type not in _STRUCTURE_CONTEXT_TYPES:
        return score, evidence
    if _context_evidence_for(paragraph_type, features, context):
        return score, evidence
    return min(score, 0.44), f"{evidence}-unverified-context"


def _soften_legacy_body_in_front_context(
    paragraph_type: ParagraphType,
    score: float,
    evidence: str,
    context: CandidateContext,
) -> tuple[float, str]:
    if paragraph_type != ParagraphType.BODY or context.document_context is None:
        return score, evidence
    if (
        context.index in context.document_context.front_positions
        or context.document_context.title_score(context.index) >= 0.44
        or context.document_context.front_metadata_kind(context.index)
    ):
        return min(score, 0.42), f"{evidence}-weak-front-context"
    return score, evidence
