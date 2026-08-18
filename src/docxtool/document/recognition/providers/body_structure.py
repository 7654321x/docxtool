"""Generic body-region structure providers."""

from __future__ import annotations

from ..model import DocumentMode, ParagraphType, SectionKind
from .base import Candidate


class Title2CandidateProvider:
    """Recognize short, unnumbered body headings in every document mode."""

    name = "body-title"

    def propose(self, block, features, context):
        before_body = (
            context.document_context is not None
            and context.document_context.before_body(context.index)
        )
        report_front_title = (
            context.mode is DocumentMode.REPORT
            and before_body
        )
        if context.previous_type not in {
            ParagraphType.BODY,
            ParagraphType.ADDRESSING,
            ParagraphType.HEADING_1,
            ParagraphType.HEADING_2,
            ParagraphType.HEADING_3,
            ParagraphType.HEADING_4,
            ParagraphType.TITLE2,
            ParagraphType.GLOSSARY_ITEM,
        }:
            if not (
                report_front_title
                and context.previous_type in {
                    ParagraphType.MAIN_TITLE,
                    ParagraphType.TITLE_CONTINUATION,
                }
            ):
                return []
        if before_body and not report_front_title:
            return []
        if (
            not features.compact_text
            or features.text_length >= 28
            or features.numbering_prefix
            or features.contains_colon
            or features.ends_with_sentence_punctuation
            or features.date_match
            or features.recipient_match
            or (
                not report_front_title
                and not (features.is_bold or features.is_docxtool_style)
            )
        ):
            return []
        return [Candidate(
            ParagraphType.TITLE2,
            0.78,
            self.name,
            ("short-body-heading",),
            section_hint=SectionKind.BODY,
        )]


class GlossaryCandidateProvider:
    """Recognize glossary headings and colon-separated glossary items."""

    name = "glossary"

    def propose(self, block, features, context):
        report_front_title = (
            context.mode is DocumentMode.REPORT
            and context.document_context is not None
            and context.document_context.before_body(context.index)
        )
        if features.compact_text in {"名词解释", "注释"} and context.previous_type in {
            ParagraphType.HEADING_1,
            ParagraphType.HEADING_2,
            ParagraphType.HEADING_3,
            ParagraphType.HEADING_4,
            ParagraphType.BODY,
            ParagraphType.TITLE2,
        } | ({ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION} if report_front_title else set()):
            return [Candidate(
                ParagraphType.GLOSSARY_TITLE,
                0.96,
                self.name,
                ("glossary-heading",),
                hard=True,
                section_hint=SectionKind.BODY,
            )]
        if context.previous_type not in {
            ParagraphType.GLOSSARY_TITLE,
            ParagraphType.GLOSSARY_ITEM,
        }:
            return []
        numbered_item = (
            features.numbering_level is not None
            or features.heading_shape_level is not None
        )
        if features.text_length < 4 or not (features.contains_colon or numbered_item):
            return []
        return [Candidate(
            ParagraphType.GLOSSARY_ITEM,
            0.96,
            self.name,
            ("glossary-colon-item" if features.contains_colon else "glossary-numbered-item",),
            hard=True,
            section_hint=SectionKind.BODY,
        )]
