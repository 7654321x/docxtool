"""Explicit numbering candidate provider."""

from __future__ import annotations

from ..model import ParagraphType
from .base import Candidate


class NumberingCandidateProvider:
    name = "numbering"

    def propose(self, block, features, context):
        if features.heading_shape_level is None or features.key_value_label:
            return []
        mapping = {1: ParagraphType.HEADING_1, 2: ParagraphType.HEADING_2, 3: ParagraphType.HEADING_3, 4: ParagraphType.HEADING_4}
        kind = mapping.get(features.heading_shape_level)
        if kind is None:
            return []
        position = context.index
        global_context = context.document_context
        family = global_context.heading_family(position)
        score = 0.72
        evidence = list(global_context.heading_reasons(position) or (f"heading-level-{features.heading_shape_level}",))
        if features.native_numbering_level_source:
            evidence.append(
                f"native-numbering-{features.native_numbering_level_source}"
            )
        if features.heading_semantic_score >= 0.8:
            score += 0.08
            evidence.append("explicit-numbering-shape")
        if family and family.count >= 2:
            score += 0.18
        if family and position in family.supported_positions:
            score += 0.06
        if not global_context.before_body(position):
            score += 0.18
        if any(
            item in evidence
            for item in (
                "numbering-duplicate",
                "numbering-reverse",
                "numbering-gap",
                "missing-parent-heading",
                "numbering-starts-after-one",
            )
        ):
            score -= 0.06
        if (
            global_context.before_body(position)
            and features.heading_shape_level == 1
            and not (family and family.count >= 2)
        ):
            score -= 0.22
            evidence.append("pre-body-heading-penalty")
        return [Candidate(
            kind,
            max(0.35, min(0.96, score)),
            self.name,
            tuple(dict.fromkeys(evidence)),
            heading_level=features.heading_shape_level,
        )]
