"""Generic body-region structure providers."""

from __future__ import annotations

from ..model import ParagraphType, SectionKind
from .base import Candidate


class Title2CandidateProvider:
    """Recognize short, unnumbered body headings in every document mode."""

    name = "body-title"

    def propose(self, block, features, context):
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
            return []
        if context.document_context is not None and context.document_context.before_body(context.index):
            return []
        if (
            not features.compact_text
            or features.text_length >= 28
            or features.numbering_prefix
            or features.contains_colon
            or features.ends_with_sentence_punctuation
            or features.date_match
            or features.recipient_match
            or not (features.is_bold or features.is_docxtool_style)
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
        if features.compact_text in {"名词解释", "注释"} and context.previous_type in {
            ParagraphType.HEADING_1,
            ParagraphType.HEADING_2,
            ParagraphType.HEADING_3,
            ParagraphType.HEADING_4,
            ParagraphType.BODY,
            ParagraphType.TITLE2,
        }:
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
        if not features.contains_colon or features.text_length < 4:
            return []
        return [Candidate(
            ParagraphType.GLOSSARY_ITEM,
            0.96,
            self.name,
            ("glossary-colon-item",),
            hard=True,
            section_hint=SectionKind.BODY,
        )]
