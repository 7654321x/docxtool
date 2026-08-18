"""Narrow structural evidence for annual-review inline headings."""

from __future__ import annotations

from ..model import DocumentMode, ParagraphType, SectionKind
from .base import Candidate


_ANNUAL_REVIEW_HEADINGS = {"一年来。", "五年来。"}


class InlineHeadingCandidateProvider:
    """Map an already segmented annual-review lead to ordinary heading one."""

    name = "inline-heading"

    def propose(self, block, features, context):
        if (
            context.mode is not DocumentMode.REPORT
            or features.compact_text not in _ANNUAL_REVIEW_HEADINGS
        ):
            return []
        return [Candidate(
            ParagraphType.HEADING_1,
            0.94,
            self.name,
            ("annual-review-heading",),
            hard=True,
            section_hint=SectionKind.BODY,
            heading_level=1,
        )]
