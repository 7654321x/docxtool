"""Semantic and document-front candidate providers."""

from __future__ import annotations

import re

from ..colon import is_standalone_addressing_text
from ..model import ParagraphType, SectionKind
from .base import Candidate


_OPENING_SPEECH_TITLE_RE = re.compile(r"^(?:[一二三四五六七八九十]+、)?在[\u4e00-\u9fffA-Za-z0-9（）()、，,.·\-]{3,70}(?:上)?的?讲话$")


class SemanticCandidateProvider:
    name = "semantic"

    def propose(self, block, features, context):
        result = []
        is_opening_speech = bool(_OPENING_SPEECH_TITLE_RE.fullmatch(features.compact_text))
        global_context = context.document_context
        score = global_context.title_score(context.index)
        reasons = global_context.title_reasons(context.index)
        follows_dispatch_continuation = (
            context.previous_type == ParagraphType.DISPATCH_NUMBER
            and str(features.legacy_type_id or "") == "title_cont"
        )
        if (score >= 0.44 or is_opening_speech) and not follows_dispatch_continuation:
            score = max(score, 0.98 if is_opening_speech else 0.0)
            result.append(Candidate(ParagraphType.MAIN_TITLE, score, self.name, reasons or ("opening-speech-title",), section_hint=SectionKind.HEADER))
        if (
            not context.boundary_before
            and context.previous_type in {ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION}
            and context.index in global_context.front_positions
            and score >= 0.48
        ):
            result.append(Candidate(ParagraphType.TITLE_CONTINUATION, max(0.86, min(0.95, score + 0.20)), self.name, ("front-title-continuation",), section_hint=SectionKind.HEADER))
        return result


class FrontMatterMetadataCandidateProvider:
    """Promote structurally supported metadata lines in the document head."""

    name = "front-metadata"

    def propose(self, block, features, context):
        global_context = context.document_context
        if global_context is None or not global_context.before_body(context.index):
            return []
        kind = global_context.front_metadata_kind(context.index)
        if kind == "role_name":
            return [Candidate(
                ParagraphType.ROLE_NAME,
                0.97,
                self.name,
                ("front-role-name-shape",),
                section_hint=SectionKind.HEADER,
            )]
        if kind == "date_line":
            return [Candidate(
                ParagraphType.DATE_LINE,
                0.97,
                self.name,
                ("front-date-shape",),
                section_hint=SectionKind.HEADER,
            )]
        if kind == "meeting_title_meta":
            return [Candidate(
                ParagraphType.MEETING_TITLE_META,
                0.97,
                self.name,
                ("front-meeting-title-metadata",),
                section_hint=SectionKind.HEADER,
            )]
        return []


class SourceListNumberingCandidateProvider:
    """Preserve short Word list headings with visual or parent-child support."""

    name = "source-list-numbering"

    def propose(self, block, features, context):
        if features.native_numbering_level is not None:
            return []
        if features.heading_shape_level is not None:
            return []
        source_features = getattr(block.raw_reference, "features", None)
        marker = str(
            getattr(source_features, "segment_numbering_features", "")
            or getattr(source_features, "numbering_prefix", "")
            or ""
        )
        match = re.fullmatch(r"@lvl_(\d+)", marker)
        if match is None:
            return []
        source_level = int(match.group(1))
        following_evidence = (
            set(context.document_context.heading_reasons(context.index + 1))
            if source_level == 0 and context.document_context is not None
            else set()
        )
        parent_of_following_heading2 = {
            "numbered-heading-level-2",
            "missing-parent-heading",
        } <= following_evidence
        bold_heading = features.is_bold or features.bold_char_ratio >= 0.65
        if (
            features.text_length > 40
            or features.key_value_label
            or features.date_match
            or features.attachment_note_match
            or is_standalone_addressing_text(features.normalized_text)
            or not (bold_heading or parent_of_following_heading2)
        ):
            return []
        level = 1 if parent_of_following_heading2 else min(source_level + 2, 4)
        evidence = [f"source-word-list-level-{source_level}"]
        if bold_heading:
            evidence.append("short-bold-list-heading")
        if parent_of_following_heading2:
            evidence.append("parent-of-following-heading2")
        paragraph_type = {
            1: ParagraphType.HEADING_1,
            2: ParagraphType.HEADING_2,
            3: ParagraphType.HEADING_3,
            4: ParagraphType.HEADING_4,
        }[level]
        return [Candidate(
            paragraph_type,
            1.0,
            self.name,
            tuple(evidence),
            hard=True,
            section_hint=SectionKind.BODY,
            heading_level=level,
        )]
