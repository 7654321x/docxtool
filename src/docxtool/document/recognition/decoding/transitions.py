"""Beam transition scoring and structural vetoes."""

from __future__ import annotations

import re

from ..candidates import Candidate
from ..features import DocumentBlock, ends_with_unicode_punctuation
from ..model import DocumentMode, ParagraphType, SectionKind
from .candidate_selection import _MEETING_LABELS
from .model import _Context


def _transition(previous: ParagraphType | None, current: Candidate, previous_section: SectionKind | None, mode: DocumentMode, boundary_before: bool) -> float:
    if boundary_before and current.paragraph_type == ParagraphType.TITLE_CONTINUATION:
        return -0.35
    if previous == ParagraphType.MAIN_TITLE and current.paragraph_type == ParagraphType.TITLE_CONTINUATION:
        return 0.18
    if previous == ParagraphType.TITLE_CONTINUATION and current.paragraph_type == ParagraphType.DISPATCH_NUMBER:
        return 0.3
    if previous in {ParagraphType.SIGNATURE_DATE, ParagraphType.SIGNATURE_ORG} and current.paragraph_type == ParagraphType.EMBEDDED_DOCUMENT_TITLE:
        return 0.2
    if current.paragraph_type == ParagraphType.EMBEDDED_DOCUMENT_TITLE and "following-chapter" in current.evidence:
        return 0.24
    if current.paragraph_type == ParagraphType.MEETING_META and previous in {ParagraphType.HEADING_1, ParagraphType.HEADING_2}:
        return 0.05
    if previous_section == SectionKind.SIGNATURE and current.section_hint == SectionKind.BODY:
        return -0.08
    if (
        current.section_hint == SectionKind.HEADER
        and "front-position" in current.evidence
    ):
        return 0.0
    if previous_section in {SectionKind.BODY, SectionKind.SIGNATURE, SectionKind.ATTACHMENT_NOTE, SectionKind.ATTACHMENT_BODY} and current.section_hint in {SectionKind.HEADER, SectionKind.DISPATCH_META}:
        return -0.40
    if mode == DocumentMode.MEETING_MINUTES and current.paragraph_type == ParagraphType.MEETING_META:
        return 0.04
    return 0.0


def _hard_veto(candidate: Candidate, features, mode: DocumentMode, context: _Context, block: DocumentBlock) -> bool:
    # Structural facts veto visually plausible headings before scoring.
    if (
        candidate.paragraph_type == ParagraphType.TITLE2
        and ends_with_unicode_punctuation(features.compact_text)
    ):
        return True
    front_metadata_kind = (
        context.document_context.front_metadata_kind(context.index)
        if context.document_context is not None
        else None
    )
    if (
        front_metadata_kind in {"role_name", "date_line", "meeting_title_meta"}
        and candidate.paragraph_type in {
            ParagraphType.MAIN_TITLE,
            ParagraphType.TITLE_CONTINUATION,
        }
    ):
        return True
    if features.dispatch_number_match and candidate.paragraph_type != ParagraphType.DISPATCH_NUMBER:
        return True
    if features.date_match and candidate.paragraph_type == ParagraphType.TITLE_CONTINUATION:
        return True
    if features.recipient_match and candidate.paragraph_type == ParagraphType.TITLE_CONTINUATION:
        return True
    if (
        candidate.paragraph_type in {ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION}
        and context.document_context is not None
        and not context.document_context.before_body(context.index)
        and not (candidate.source == "core" and candidate.score >= 0.85)
    ):
        return True
    if (
        features.key_value_label in _MEETING_LABELS
        and not features.numbered_heading2_colon_inline_body
        and candidate.paragraph_type in {
            ParagraphType.HEADING_1, ParagraphType.HEADING_2,
            ParagraphType.HEADING_3, ParagraphType.HEADING_4,
        }
    ):
        return True
    heading_levels = {
        ParagraphType.HEADING_1: 1,
        ParagraphType.HEADING_2: 2,
        ParagraphType.HEADING_3: 3,
        ParagraphType.HEADING_4: 4,
    }
    previous_level = heading_levels.get(context.previous_type)
    current_level = heading_levels.get(candidate.paragraph_type)
    if current_level is not None and (
        features.date_match
        or features.attachment_note_match
        or features.recipient_match
        or (features.key_value_label and not features.numbered_heading2_colon_inline_body)
        or (
            features.colon_explanatory_body
            and not features.numbered_heading2_colon_inline_body
        )
        or features.native_numbering_body_list
        or re.fullmatch(
            r"附件[0-9一二三四五六七八九十百千]*",
            features.compact_text,
        )
    ):
        return True
    if previous_level is not None and current_level is not None and current_level > previous_level + 1:
        return True
    if (
        context.previous_type in {ParagraphType.ATTACHMENT_NOTE, ParagraphType.ATTACHMENT_NOTE_ITEM}
        and features.numbering_prefix
        and candidate.paragraph_type in heading_levels
    ):
        return True
    return False
