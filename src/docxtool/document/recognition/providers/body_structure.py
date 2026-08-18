"""Generic body-region structure providers."""

from __future__ import annotations

from ..model import DocumentMode, ParagraphType, SectionKind
from .base import Candidate, _glossary_context_active


def _looks_like_glossary_heading(features) -> bool:
    """Return whether a short heading contains a glossary marker."""
    text = str(features.compact_text or "")
    return bool(
        text
        and len(text) <= 20
        and not features.numbering_prefix
        and not features.contains_colon
        and not features.ends_with_sentence_punctuation
        and ("名词解释" in text or "注释" in text)
    )


class Title2CandidateProvider:
    """Recognize short, unnumbered body headings in every document mode."""

    name = "body-title"

    def propose(self, block, features, context):
        following = (
            context.following_features[0]
            if context.following_features
            else None
        )
        report_middle_body_title = bool(
            context.mode is DocumentMode.REPORT
            and context.previous_type == ParagraphType.BODY
            and following is not None
            and following.compact_text
            and not following.heading_shape_level
            and (
                following.text_length >= 34
                or (
                    following.ends_with_sentence_punctuation
                    and following.text_length >= 12
                )
            )
        )
        before_body = (
            context.document_context is not None
            and context.document_context.before_body(context.index)
        )
        front_title_candidate = (
            before_body
            and context.previous_type in {
                ParagraphType.MAIN_TITLE,
                ParagraphType.TITLE_CONTINUATION,
            }
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
            if not front_title_candidate:
                return []
        if before_body and not front_title_candidate:
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
                not front_title_candidate
                and not report_middle_body_title
                and not (features.is_bold or features.is_docxtool_style)
            )
        ):
            return []
        if front_title_candidate and context.document_context is not None:
            title_score = context.document_context.title_score(context.index)
            if (
                title_score >= 0.48
                and context.index in context.document_context.front_positions
            ):
                return []
        score = 0.64
        evidence = ["short-body-heading"]
        if front_title_candidate:
            evidence.append("front-body-position")
        if context.mode is DocumentMode.REPORT:
            score += 0.08
            evidence.append("report-mode-prior")
        if report_middle_body_title:
            score += 0.10
            evidence.append("report-middle-body-position")
        if features.is_bold or features.is_docxtool_style:
            score += 0.08
        return [Candidate(
            ParagraphType.TITLE2,
            score,
            self.name,
            tuple(evidence),
            section_hint=SectionKind.BODY,
        )]


class GlossaryCandidateProvider:
    """Recognize glossary headings and colon-separated glossary items."""

    name = "glossary"

    def propose(self, block, features, context):
        before_body = (
            context.document_context is not None
            and context.document_context.before_body(context.index)
        )
        front_title_candidate = (
            before_body
            and context.previous_type in {
                ParagraphType.MAIN_TITLE,
                ParagraphType.TITLE_CONTINUATION,
            }
        )
        if _looks_like_glossary_heading(features) and context.previous_type in {
            ParagraphType.HEADING_1,
            ParagraphType.HEADING_2,
            ParagraphType.HEADING_3,
            ParagraphType.HEADING_4,
            ParagraphType.BODY,
            ParagraphType.TITLE2,
        } | ({ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION} if front_title_candidate else set()):
            return [Candidate(
                ParagraphType.GLOSSARY_TITLE,
                0.96,
                self.name,
                ("glossary-heading",),
                hard=True,
                section_hint=SectionKind.BODY,
            )]
        if not _glossary_context_active(context):
            return []
        numbered_item = features.heading_shape_level == 3
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
