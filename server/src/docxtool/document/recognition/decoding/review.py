"""User-facing review assessment derived from selected candidates."""

from __future__ import annotations

from ..candidates import Candidate
from ..config import RecognitionConfig
from ..model import ParagraphType


_HEADING_TYPES = frozenset(
    {
        ParagraphType.HEADING_1,
        ParagraphType.HEADING_2,
        ParagraphType.HEADING_3,
        ParagraphType.HEADING_4,
    }
)
_HEADING_CONFLICT_EVIDENCE = frozenset(
    {
        "numbering-duplicate",
        "numbering-reverse",
        "numbering-gap",
        "missing-parent-heading",
        "numbering-starts-after-one",
    }
)
_STRUCTURE_SENSITIVE_TYPES = frozenset(
    {
        ParagraphType.MAIN_TITLE,
        ParagraphType.TITLE_CONTINUATION,
        ParagraphType.DISPATCH_NUMBER,
        ParagraphType.RECIPIENT,
        ParagraphType.SIGNATURE_ORG,
        ParagraphType.SIGNATURE_DATE,
        ParagraphType.ATTACHMENT_NOTE,
        ParagraphType.ATTACHMENT_NOTE_ITEM,
        ParagraphType.ATTACHMENT_PAGE_MARK,
        ParagraphType.ATTACHMENT_TITLE,
        ParagraphType.ATTACHMENT_BODY,
    }
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _review_evidence(
    selected: Candidate | None,
    features,
    legacy_type_id: str,
    compatible: str | None,
    context_evidence=(),
) -> tuple[float, list[str], bool]:
    """Return explainable evidence strength without treating softmax as certainty.

    Candidate scores are ranking values assembled from several providers.  They
    are intentionally close together, so their raw softmax distribution is a
    poor user-facing confidence measure.  This helper instead records whether
    the selected type has a concrete structural signal or stable agreement with
    the existing classification.
    """
    if selected is None:
        return 0.0, ["selection-missing"], False

    evidence = list(selected.evidence)
    direct = selected.hard
    strength = 0.45
    if selected.hard:
        strength = 1.0
        evidence.append("hard-structure")
    elif selected.paragraph_type in _HEADING_TYPES and features.heading_shape_level:
        evidence.append("explicit-numbering")
        if any(item in context_evidence for item in _HEADING_CONFLICT_EVIDENCE):
            strength = max(strength, 0.58)
            evidence.append("heading-sequence-conflict")
        elif (
            selected.paragraph_type == ParagraphType.HEADING_1
            and "parallel-heading-family" not in context_evidence
            and "nested-heading-support" not in context_evidence
        ):
            strength = max(strength, 0.70)
            evidence.append("single-heading-family")
        else:
            direct = True
            strength = max(strength, 0.93)
    elif selected.paragraph_type == ParagraphType.KEY_VALUE and features.key_value_label:
        direct = True
        strength = max(strength, 0.92)
        evidence.append("explicit-key-value")
    elif selected.paragraph_type == ParagraphType.SIGNATURE_DATE and features.date_match:
        direct = True
        strength = max(strength, 0.90)
        evidence.append("date-shape")
    elif selected.paragraph_type == ParagraphType.SIGNATURE_ORG and features.signature_org_match:
        direct = True
        strength = max(strength, 0.86)
        evidence.append("signature-shape")
    elif selected.paragraph_type in {ParagraphType.ROLE_NAME, ParagraphType.DATE_LINE} and any(
        item in evidence for item in {"front-role-name-shape", "front-date-shape"}
    ):
        direct = True
        strength = max(strength, 0.93)
        evidence.append("front-metadata-shape")
    elif (
        selected.paragraph_type in {ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION}
        and features.title_shape_score >= 0.8
    ):
        strength = max(strength, 0.80)
        evidence.append("title-shape")

    if compatible and compatible == legacy_type_id:
        evidence.append("legacy-agreement")
    elif compatible and legacy_type_id:
        evidence.append("legacy-reclassified")

    # Preserve order while making the public diagnostic deterministic.
    return strength, list(dict.fromkeys(evidence)), direct


def _review_assessment(
    selected: Candidate | None,
    features,
    legacy_type_id: str,
    compatible: str | None,
    mapping_failed: bool,
    final_score: float,
    margin: float | None,
    config: RecognitionConfig,
    execution_mode: str,
    context_evidence=(),
) -> tuple[float, str, list[str], list[str]]:
    """Classify review risk independently from candidate ranking diagnostics."""
    evidence_strength, evidence_summary, direct_evidence = _review_evidence(
        selected, features, legacy_type_id, compatible, context_evidence
    )
    score_strength = _clamp((final_score - 0.50) / 0.45)
    margin_strength = 1.0 if margin is None else _clamp((margin + 0.02) / 0.20)
    review_confidence = round(
        _clamp(0.35 * score_strength + 0.25 * margin_strength + 0.40 * evidence_strength),
        4,
    )
    type_changed = bool(compatible and compatible != legacy_type_id)
    sensitive_change = bool(selected and selected.paragraph_type in _STRUCTURE_SENSITIVE_TYPES)
    close_competition = margin is not None and margin < config.review_margin
    heading_conflict = bool(
        context_evidence and any(item in context_evidence for item in _HEADING_CONFLICT_EVIDENCE)
    )
    reasons: list[str] = []

    if mapping_failed:
        reasons.append("TYPE_MAPPING_FAILED")
        level = "critical_review"
    elif heading_conflict:
        reasons.append("HEADING_SEQUENCE_CONFLICT")
        level = "review"
    elif type_changed and not direct_evidence and sensitive_change:
        reasons.extend(("LEGACY_TYPE_CONFLICT", "STRUCTURE_SENSITIVE_CHANGE"))
        level = "critical_review"
    elif type_changed and not direct_evidence:
        reasons.append("LEGACY_TYPE_CONFLICT")
        level = "review"
    elif not direct_evidence and close_competition:
        reasons.append("SMALL_CANDIDATE_MARGIN")
        level = "review"
    elif not direct_evidence and review_confidence < config.review_low_score:
        reasons.append("WEAK_EVIDENCE")
        level = "review"
    elif type_changed:
        # A decisive structural reclassification is recorded, but does not
        # create noisy manual-review work for the user.
        reasons.append("STRUCTURE_CONFIRMED_RECLASSIFICATION")
        level = "info"
    elif execution_mode == "shadow":
        reasons.append("SHADOW_RESULT_NOT_APPLIED")
        level = "info"
    else:
        level = "confirmed"

    return review_confidence, level, reasons, evidence_summary
