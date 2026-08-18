"""Structural candidate provider."""

from __future__ import annotations

import re

from ..colon import is_standalone_addressing_text
from ..model import ParagraphType, SectionKind
from .base import Candidate, _body_like_candidate


_ATTACHMENT_PAGE_MARK_RE = re.compile(r"^附件\s*[0-9一二三四五六七八九十百千]*$")


class StructuralCandidateProvider:
    name = "structural"

    def propose(self, block, features, context):
        result = []
        if block.kind == "caption":
            return [Candidate(ParagraphType.CAPTION, 1.0, self.name, ("object-caption",), hard=True, section_hint=SectionKind.BODY)]
        if features.compact_text.startswith(("图", "表")):
            marker = features.compact_text[1:]
            if marker and marker[0] in "0123456789一二三四五六七八九十百":
                return [Candidate(
                    ParagraphType.BODY,
                    1.0,
                    self.name,
                    ("unbound-caption-like-body",),
                    hard=True,
                    section_hint=SectionKind.BODY,
                )]
        if features.dispatch_number_match:
            result.append(Candidate(ParagraphType.DISPATCH_NUMBER, 1.0, self.name, ("dispatch-number",), hard=True, section_hint=SectionKind.DISPATCH_META))
        if (
            _ATTACHMENT_PAGE_MARK_RE.fullmatch(features.compact_text)
            and context.previous_type in {
                ParagraphType.ATTACHMENT_NOTE,
                ParagraphType.ATTACHMENT_NOTE_ITEM,
                ParagraphType.SIGNATURE_DATE,
                ParagraphType.ATTACHMENT_TITLE,
                ParagraphType.ATTACHMENT_BODY,
            }
        ):
            result.append(Candidate(
                ParagraphType.ATTACHMENT_PAGE_MARK,
                1.0,
                self.name,
                ("attachment-page-boundary",),
                hard=True,
                section_hint=SectionKind.ATTACHMENT_BODY,
            ))
        if (
            context.previous_type == ParagraphType.ATTACHMENT_PAGE_MARK
            and features.compact_text
            and features.text_length <= 40
            and not features.contains_colon
            and features.heading_shape_level is None
        ):
            result.append(Candidate(
                ParagraphType.ATTACHMENT_TITLE,
                0.98,
                self.name,
                ("after-attachment-page-mark",),
                hard=True,
                section_hint=SectionKind.ATTACHMENT_BODY,
            ))
        elif (
            context.previous_type == ParagraphType.ATTACHMENT_PAGE_MARK
            and features.compact_text
        ):
            result.append(Candidate(
                ParagraphType.ATTACHMENT_BODY,
                0.97,
                self.name,
                ("after-attachment-page-mark-body",),
                hard=True,
                section_hint=SectionKind.ATTACHMENT_BODY,
            ))
        if (
            context.previous_type in {
                ParagraphType.ATTACHMENT_TITLE,
                ParagraphType.ATTACHMENT_BODY,
            }
            and features.compact_text
            and not _ATTACHMENT_PAGE_MARK_RE.fullmatch(features.compact_text)
        ):
            result.append(Candidate(
                ParagraphType.ATTACHMENT_BODY,
                1.0,
                self.name,
                ("inside-attachment-body",),
                hard=True,
                section_hint=SectionKind.ATTACHMENT_BODY,
            ))
        signature_date_evidence = (
            context.document_context.signature_date_reasons(context.index)
            if context.document_context is not None else ()
        )
        if signature_date_evidence:
            result.append(Candidate(
                ParagraphType.SIGNATURE_DATE,
                0.97,
                self.name,
                signature_date_evidence,
                hard=True,
                section_hint=SectionKind.SIGNATURE,
            ))
        elif features.date_match:
            result.append(Candidate(
                ParagraphType.BODY,
                0.76,
                self.name,
                ("date-without-signature-context",),
                section_hint=SectionKind.BODY,
            ))
        signature_evidence = (
            context.document_context.signature_org_reasons(context.index)
            if context.document_context is not None else ()
        )
        if signature_evidence:
            result.append(Candidate(
                ParagraphType.SIGNATURE_ORG,
                0.97,
                self.name,
                signature_evidence,
                hard=True,
                section_hint=SectionKind.SIGNATURE,
            ))
        if is_standalone_addressing_text(features.normalized_text):
            result.append(Candidate(
                ParagraphType.ADDRESSING,
                0.99,
                self.name,
                ("standalone-addressing",),
                hard=True,
                section_hint=SectionKind.RECIPIENT,
            ))
        if features.colon_inline_addressing_body:
            result.append(Candidate(
                ParagraphType.ADDRESSING,
                0.98,
                self.name,
                ("inline-addressing-boundary",),
                section_hint=SectionKind.RECIPIENT,
            ))
        elif (
            features.recipient_match
            and context.document_context is not None
            and (
                context.index == 0
                or context.document_context.before_body(context.index)
                or context.index in context.document_context.front_positions
            )
        ):
            result.append(Candidate(ParagraphType.RECIPIENT, 0.95, self.name, ("front-recipient",), hard=True, section_hint=SectionKind.RECIPIENT))
        if (
            (
                features.colon_explanatory_body
                and not features.numbered_heading2_colon_inline_body
            )
            or (
                features.colon_body_label_candidate
                and context.document_context is not None
                and not context.document_context.before_body(context.index)
            )
        ):
            result.append(Candidate(
                ParagraphType.BODY,
                0.98,
                self.name,
                ("colon-explanatory-body" if features.colon_explanatory_body else "body-organization-label",),
                hard=True,
                section_hint=SectionKind.BODY,
            ))
        if features.attachment_note_match:
            attachment_evidence = (
                context.document_context.attachment_note_reasons(context.index)
                if context.document_context is not None else ()
            )
            if attachment_evidence:
                result.append(Candidate(
                    ParagraphType.ATTACHMENT_NOTE,
                    0.98,
                    self.name,
                    attachment_evidence,
                    hard=True,
                    section_hint=SectionKind.ATTACHMENT_NOTE,
                ))
            else:
                result.append(Candidate(
                    ParagraphType.ATTACHMENT_NOTE,
                    0.52,
                    self.name,
                    ("attachment-keyword-unverified-context",),
                    section_hint=SectionKind.ATTACHMENT_NOTE,
                ))
                result.append(Candidate(
                    ParagraphType.BODY,
                    0.94,
                    self.name,
                    ("attachment-keyword-without-tail-context",),
                    hard=True,
                    section_hint=SectionKind.BODY,
                ))
        attachment_item_evidence = (
            context.document_context.attachment_item_reasons(context.index)
            if context.document_context is not None else ()
        )
        if attachment_item_evidence:
            result.append(Candidate(
                ParagraphType.ATTACHMENT_NOTE_ITEM,
                0.97,
                self.name,
                attachment_item_evidence,
                hard=True,
                section_hint=SectionKind.ATTACHMENT_NOTE,
            ))
        if _body_like_candidate(features):
            result.append(Candidate(
                ParagraphType.BODY,
                0.82,
                self.name,
                ("body-prose-shape",),
                section_hint=SectionKind.BODY,
            ))
        return result
