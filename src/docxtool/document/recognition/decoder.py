"""Deterministic global resolver for paragraph recognition."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
import re
from typing import Any

from .candidates import Candidate, CandidateContext, DEFAULT_PROVIDERS
from .compatibility import to_paragraph_type
from .config import DEFAULT_CONFIG, RecognitionConfig
from .features import DocumentBlock, detect_mode, extract_blocks, extract_features
from .global_context import DocumentContext, analyze_document_context
from .model import DocumentMode, ParagraphType, RecognitionSummary, SectionKind
from .validators import validate_diagnostics
from .version import RECOGNITION_DIAGNOSTIC_SCHEMA_VERSION, RECOGNITION_ENGINE_VERSION, RECOGNITION_VERSION_TAG


_EMBEDDED_TITLE_RE = re.compile(r"^.{2,32}(?:规划|方案|办法|规定|报告|意见|要点|决定|通知)$")
_SOURCE_NOTE_RE = re.compile(r"^(?:来源|注|说明|备注)\s*[:：]")
_MEETING_LABELS = frozenset({"时间", "地点", "主持", "记录", "出席", "缺席", "列席", "参会", "参加", "议题", "议定事项", "会议名称", "会议时间", "会议地点"})
_HEADING_TYPES = frozenset({
    ParagraphType.HEADING_1,
    ParagraphType.HEADING_2,
    ParagraphType.HEADING_3,
    ParagraphType.HEADING_4,
})
_STRUCTURE_SENSITIVE_TYPES = frozenset({
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
})
_FRONT_METADATA_LEGACY_TYPES = frozenset({
    "role_name",
    "author_line",
    "date_line",
    "meeting_line",
    "location_line",
})


@dataclass(frozen=True)
class _Context(CandidateContext):
    mode: DocumentMode
    previous_type: ParagraphType | None
    index: int
    boundary_before: bool = False
    document_context: DocumentContext | None = None


@dataclass(frozen=True)
class _Beam:
    score: float
    types: tuple[ParagraphType, ...]
    reasons: tuple[str, ...]
    sections: tuple[SectionKind, ...]


def _legacy_type(value: str) -> ParagraphType:
    aliases = {
        "title": ParagraphType.MAIN_TITLE,
        "title_cont": ParagraphType.TITLE_CONTINUATION,
        "heading1": ParagraphType.HEADING_1,
        "heading2": ParagraphType.HEADING_2,
        "heading3": ParagraphType.HEADING_3,
        "heading4": ParagraphType.HEADING_4,
        "sign_org": ParagraphType.SIGNATURE_ORG,
        "sign_date": ParagraphType.SIGNATURE_DATE,
        "attachment_note_item": ParagraphType.ATTACHMENT_NOTE,
    }
    return aliases.get(value, ParagraphType.BODY)


def _mode_as_legacy(mode: DocumentMode) -> str:
    return {DocumentMode.REPORT: "REPORT", DocumentMode.NORMAL: "NORMAL", DocumentMode.UNKNOWN: "UNKNOWN"}.get(mode, mode.value.upper())


def _extra_candidates(block: DocumentBlock, features, context: _Context, previous_features, lookahead=()) -> list[Candidate]:
    result: list[Candidate] = []
    text = features.compact_text
    if features.source_note_match:
        result.append(Candidate(ParagraphType.SOURCE_NOTE, 0.97, "structural", ("source-note",), hard=True, section_hint=SectionKind.SOURCE_NOTE))
    if features.date_match:
        result.append(Candidate(ParagraphType.SIGNATURE_DATE, 0.85, "structural", ("date-shape",), section_hint=SectionKind.SIGNATURE))
    if features.recipient_match:
        result.append(Candidate(ParagraphType.RECIPIENT, 0.95, "structural", ("recipient-boundary",), hard=True, section_hint=SectionKind.RECIPIENT))
    has_following_chapter = any(re.match(r"^(?:第[一二三四五六七八九十百0-9]+章|[一二三四五六七八九十]+、)", item.compact_text) for item in lookahead)
    if previous_features and (previous_features.date_match or "本文有删减" in previous_features.compact_text or "本文有删减" in text):
        if _EMBEDDED_TITLE_RE.fullmatch(text):
            score = 0.86 if has_following_chapter else 0.5
            result.append(Candidate(ParagraphType.EMBEDDED_DOCUMENT_TITLE, score, "embedded-document", ("after-signature-or-source-note", "following-chapter" if has_following_chapter else "no-following-chapter"), hard=False, section_hint=SectionKind.EMBEDDED_DOCUMENT))
    if context.mode == DocumentMode.MEETING_MINUTES and features.key_value_label in _MEETING_LABELS:
        result.append(Candidate(ParagraphType.MEETING_META, 1.0, "meeting", ("meeting-metadata",), hard=True, section_hint=SectionKind.MEETING_META))
    return result


def _candidates(block: DocumentBlock, features, context: _Context, previous_features, lookahead=()) -> list[Candidate]:
    result: list[Candidate] = []
    for provider in DEFAULT_PROVIDERS:
        result.extend(provider.propose(block, features, context))
    result.extend(_extra_candidates(block, features, context, previous_features, lookahead))
    # One provider may emit the same type more than once. Keep its strongest,
    # deterministic candidate and retain the evidence from the strongest source.
    strongest: dict[ParagraphType, Candidate] = {}
    for candidate in result:
        old = strongest.get(candidate.paragraph_type)
        if old is None or (candidate.hard, candidate.score, candidate.source) > (old.hard, old.score, old.source):
            strongest[candidate.paragraph_type] = candidate
    if not strongest:
        strongest[ParagraphType.BODY] = Candidate(ParagraphType.BODY, 0.5, "fallback", ("no-candidate",), section_hint=SectionKind.BODY)
    return sorted(strongest.values(), key=lambda item: (-item.hard, -item.score, item.paragraph_type.value))


def _limit_candidates(options: list[Candidate], config: RecognitionConfig) -> list[Candidate]:
    hard = [item for item in options if item.hard]
    soft = [item for item in options if not item.hard]
    return hard + soft[:max(0, config.max_candidates_per_paragraph - len(hard))]


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
    if previous_section in {SectionKind.BODY, SectionKind.SIGNATURE, SectionKind.ATTACHMENT_NOTE, SectionKind.ATTACHMENT_BODY} and current.section_hint in {SectionKind.HEADER, SectionKind.DISPATCH_META}:
        return -0.40
    if mode == DocumentMode.MEETING_MINUTES and current.paragraph_type == ParagraphType.MEETING_META:
        return 0.04
    return 0.0


def _hard_veto(candidate: Candidate, features, mode: DocumentMode, context: _Context, block: DocumentBlock) -> bool:
    # Structural facts veto visually plausible headings before scoring.
    if features.dispatch_number_match and candidate.paragraph_type != ParagraphType.DISPATCH_NUMBER:
        return True
    if features.date_match and candidate.paragraph_type == ParagraphType.TITLE_CONTINUATION:
        return True
    if features.recipient_match and candidate.paragraph_type == ParagraphType.TITLE_CONTINUATION:
        return True
    if (
        str(features.legacy_type_id or "") in _FRONT_METADATA_LEGACY_TYPES
        and candidate.paragraph_type in {ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION}
        and context.document_context is not None
        and context.index in context.document_context.front_positions
    ):
        # Do not turn a stable post-title role/date line into another title
        # merely because its source formatting was copied from the title.
        return True
    if (
        candidate.paragraph_type in {ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION}
        and context.document_context is not None
        and not context.document_context.before_body(context.index)
        and not (candidate.source == "core" and candidate.score >= 0.85)
    ):
        return True
    if features.key_value_label in _MEETING_LABELS and candidate.paragraph_type in {ParagraphType.HEADING_1, ParagraphType.HEADING_2, ParagraphType.HEADING_3, ParagraphType.HEADING_4}:
        return True
    if mode == DocumentMode.MEETING_MINUTES and features.key_value_label in _MEETING_LABELS and candidate.paragraph_type != ParagraphType.MEETING_META:
        return True
    heading_levels = {
        ParagraphType.HEADING_1: 1,
        ParagraphType.HEADING_2: 2,
        ParagraphType.HEADING_3: 3,
        ParagraphType.HEADING_4: 4,
    }
    previous_level = heading_levels.get(context.previous_type)
    current_level = heading_levels.get(candidate.paragraph_type)
    if previous_level is not None and current_level is not None and current_level > previous_level + 1:
        return True
    if (
        context.previous_type in {ParagraphType.ATTACHMENT_NOTE, ParagraphType.ATTACHMENT_NOTE_ITEM}
        and features.numbering_prefix
        and candidate.paragraph_type in heading_levels
    ):
        return True
    if candidate.paragraph_type == ParagraphType.SIGNATURE_DATE:
        paragraph = block.raw_reference
        meta = getattr(paragraph, "meta", {}) or {}
        stored = meta.get("legacy_type_id")
        if isinstance(stored, dict):
            legacy_record = stored.get("value", "")
        else:
            legacy_record = stored or getattr(paragraph, "type_id", "")
        if legacy_record not in {"sign_date", "signature_date"} and context.previous_type != ParagraphType.SIGNATURE_ORG:
            return True
    return False


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _review_evidence(selected: Candidate | None, features, legacy_type_id: str, compatible: str | None, context_evidence=()) -> tuple[float, list[str], bool]:
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
        if (
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
    elif (
        selected.paragraph_type in {ParagraphType.ROLE_NAME, ParagraphType.DATE_LINE}
        and any(item in evidence for item in {"front-role-name-shape", "front-date-shape"})
    ):
        direct = True
        strength = max(strength, 0.93)
        evidence.append("front-metadata-shape")
    elif selected.paragraph_type in {ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION} and features.title_shape_score >= 0.8:
        strength = max(strength, 0.80)
        evidence.append("title-shape")

    if compatible and compatible == legacy_type_id:
        strength = max(strength, 0.84)
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
    reasons: list[str] = []

    if mapping_failed:
        reasons.append("TYPE_MAPPING_FAILED")
        level = "critical_review"
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


def apply_recognition(data: Any, config: RecognitionConfig | None = None) -> None:
    """Resolve all text blocks using a width-12 beam and preserve diagnostics."""
    config = config or DEFAULT_CONFIG
    blocks = extract_blocks(data)
    execution_mode = config.mode
    paragraph_blocks = [block for block in blocks if block.paragraph_index is not None and block.kind in {"paragraph", "empty", "caption"}]
    boundary_prefix = [0]
    for item in blocks:
        boundary_prefix.append(boundary_prefix[-1] + int(item.kind in {"table", "image", "page_break", "section_break"}))
    extracted = []
    for pos, block in enumerate(paragraph_blocks):
        previous = paragraph_blocks[pos - 1] if pos else None
        following = paragraph_blocks[pos + 1] if pos + 1 < len(paragraph_blocks) else None
        extracted.append(extract_features(block, previous, following))
    document_context = analyze_document_context(extracted)
    legacy_document_mode = getattr(data, "doc_mode", "")
    decision = detect_mode(extracted, legacy_document_mode)
    mode = decision.mode
    beams = [_Beam(0.0, (), (), ())]
    candidate_trace: list[dict[str, Any]] = []
    candidate_summary: dict[int, tuple[Candidate, ...]] = {}
    for pos, (block, features) in enumerate(zip(paragraph_blocks, extracted)):
        previous_features = extracted[pos - 1] if pos else None
        next_beams: list[_Beam] = []
        boundary_start = paragraph_blocks[pos - 1].index + 1 if pos else 0
        boundary_before = boundary_prefix[block.index] > boundary_prefix[boundary_start]
        trace_context = _Context(mode, beams[0].types[-1] if beams[0].types else None, pos, boundary_before, document_context)
        lookahead = extracted[pos + 1:pos + 9]
        trace_options = _limit_candidates(_candidates(block, features, trace_context, previous_features, lookahead), config)
        candidate_summary[features.paragraph_index] = tuple(trace_options)
        if config.enable_diagnostics:
            candidate_trace.append({"paragraph_index": features.paragraph_index, "candidate_count": len(trace_options), "candidates": [{"type": item.paragraph_type.value, "score": item.score, "source": item.source, "hard": item.hard, "evidence": item.evidence, "vetoes": sorted(value.value for value in item.vetoes)} for item in trace_options], "boundary_before": boundary_before})
        for beam in beams:
            context = _Context(mode, beam.types[-1] if beam.types else None, pos, boundary_before, document_context)
            options = _limit_candidates(_candidates(block, features, context, previous_features, lookahead), config)
            hard_types = {item.paragraph_type for item in options if item.hard}
            for candidate in options:
                if hard_types and candidate.paragraph_type not in hard_types:
                    continue
                if _hard_veto(candidate, features, mode, context, block):
                    continue
                section = candidate.section_hint or SectionKind.BODY
                next_beams.append(_Beam(beam.score + candidate.score + _transition(context.previous_type, candidate, beam.sections[-1] if beam.sections else None, mode, boundary_before), beam.types + (candidate.paragraph_type,), beam.reasons + (f"{candidate.source}:{','.join(candidate.evidence)}",), beam.sections + (section,)))
        if not next_beams:
            # A malformed candidate provider must not make import fail.
            next_beams = [_Beam(beam.score, beam.types + (ParagraphType.BODY,), beam.reasons + ("fallback:hard-veto",), beam.sections + (SectionKind.BODY,)) for beam in beams]
        next_beams.sort(key=lambda item: (-item.score, tuple(value.value for value in item.types), item.reasons))
        beams = next_beams[:config.beam_width]
    diagnostics = []
    if beams:
        best = beams[0]
        for position, (block, features, type_value, reason, section) in enumerate(zip(paragraph_blocks, extracted, best.types, best.reasons, best.sections)):
            paragraph = getattr(block, "raw_reference", None)
            if paragraph is None:
                continue
            existing_meta = dict(getattr(paragraph, "meta", {}) or {})
            legacy_record = existing_meta.get("legacy_type_id")
            legacy_type_id = (legacy_record.get("value") if isinstance(legacy_record, dict) else legacy_record) or paragraph.type_id
            compatible = to_paragraph_type(type_value)
            mapping_failed = compatible is None
            mapping_applied = execution_mode == "authoritative" and not mapping_failed
            if mapping_applied:
                paragraph.type_id = compatible
            final_type_id = paragraph.type_id
            meta = existing_meta
            if not isinstance(meta.get("legacy_type_id"), dict):
                meta["legacy_type_id"] = {"value": legacy_type_id, "source": "observed_input", "recognition_version": RECOGNITION_VERSION_TAG}
            options = candidate_summary[features.paragraph_index]
            selected = next((item for item in options if item.paragraph_type == type_value), None)
            final_score = selected.score if selected else 0.0
            scores = [item.score for item in options]
            max_score = max(scores, default=0.0)
            weights = [math.exp(score - max_score) for score in scores]
            denominator = sum(weights)
            selected_index = next((index for index, item in enumerate(options) if item.paragraph_type == type_value), None)
            local_confidence = (
                weights[selected_index] / denominator
                if selected_index is not None and denominator > 0
                else 0.0
            )
            competing_scores = sorted((item.score for item in options if item.paragraph_type != type_value), reverse=True)
            margin = final_score - competing_scores[0] if competing_scores else None
            previous_type = best.types[position - 1] if position else None
            previous_section = best.sections[position - 1] if position else None
            boundary_start = paragraph_blocks[position - 1].index + 1 if position else 0
            boundary_before = boundary_prefix[block.index] > boundary_prefix[boundary_start]
            transition_contribution = _transition(
                previous_type,
                selected or Candidate(type_value, final_score, "selected"),
                previous_section,
                mode,
                boundary_before,
            )
            review_confidence, review_level, review_reasons, evidence_summary = _review_assessment(
                selected,
                features,
                legacy_type_id,
                compatible,
                mapping_failed,
                final_score,
                margin,
                config,
                execution_mode,
                document_context.heading_reasons(position),
            )
            meta.update({
                "recognition_type": type_value.value,
                "recognized_type": type_value.value,
                "recognition_section": section.value,
                "recognition_provider": reason,
                "recognition_mode": execution_mode,
                "document_mode": mode.value,
                # This remains the raw candidate-distribution diagnostic for
                # backwards compatibility.  It must not be presented as the
                # user-facing certainty of the final recognition result.
                "recognition_confidence": round(local_confidence, 4),
                "review_confidence": review_confidence,
                "review_level": review_level,
                "recognition_evidence": evidence_summary,
                "mapping_applied": mapping_applied,
                "mapping_failed": mapping_failed,
                "final_type": final_type_id,
            })
            if mode != DocumentMode.REPORT:
                meta.pop("report_first_sentence_bold", None)
            paragraph.meta = meta
            diagnostics.append({
                "paragraph_index": features.paragraph_index,
                "block_index": block.index,
                "text_preview": hashlib.sha256(features.normalized_text.encode("utf-8")).hexdigest()[:config.text_preview_length],
                "document_mode": mode.value,
                "recognition_mode": execution_mode,
                "result_applied": execution_mode == "authoritative",
                "state_before": previous_section.value if previous_section else SectionKind.BODY.value,
                "state_after": section.value,
                "front_matter": position in document_context.front_positions,
                "body_start": document_context.body_start == position,
                "body_start_reason": document_context.body_start_reason if document_context.body_start == position else "",
                "title_context_evidence": list(document_context.title_reasons(position)),
                "heading_context_evidence": list(document_context.heading_reasons(position)),
                "candidate_count": len(options),
                "candidate_types": [item.paragraph_type.value for item in options],
                "provider": reason,
                "legacy_type": legacy_type_id,
                "legacy_type_id": legacy_type_id,
                "recognized_type": type_value.value,
                "final_type": final_type_id,
                "mapping_applied": mapping_applied,
                "mapping_failed": mapping_failed,
                "recognition_confidence": round(local_confidence, 4),
                "review_confidence": review_confidence,
                "review_level": review_level,
                "evidence_summary": evidence_summary,
                "selected_candidate_score": round(final_score, 4),
                "document_path_score": round(best.score, 4),
                "transition_contribution": round(transition_contribution, 4),
                "final_score": round(final_score, 4),
                "candidate_margin": round(margin, 4) if margin is not None else None,
                "single_candidate": len(options) == 1,
                "needs_review": review_level in {"review", "critical_review"},
                "review_reasons": review_reasons,
                "validator_actions": [],
            })
    if execution_mode == "authoritative":
        setattr(data, "doc_mode", _mode_as_legacy(mode))
    report = {"engine_version": RECOGNITION_ENGINE_VERSION, "schema_version": RECOGNITION_DIAGNOSTIC_SCHEMA_VERSION, "config": {"mode": execution_mode, "beam_width": config.beam_width, "max_candidates_per_paragraph": config.max_candidates_per_paragraph, "diagnostics": config.enable_diagnostics, "review_low_score": config.review_low_score, "review_margin": config.review_margin}, "recognition_mode": execution_mode, "result_applied": execution_mode == "authoritative", "mode": mode.value, "mode_confidence": decision.confidence, "mode_evidence": decision.evidence, "beam_width": config.beam_width, "blocks": [{"index": block.index, "kind": block.kind, "paragraph_index": block.paragraph_index} for block in blocks], "candidate_trace": candidate_trace, "paragraphs": diagnostics, "document_context": document_context.diagnostic_summary()}
    report["validation"] = validate_diagnostics(report)
    candidate_counts = [item["candidate_count"] for item in diagnostics]
    hard_count = sum(any(candidate.hard for candidate in options) for options in candidate_summary.values())
    provider_counts: dict[str, int] = {}
    selected_provider_counts: dict[str, int] = {}
    for options in candidate_summary.values():
        for candidate in options:
            provider_counts[candidate.source] = provider_counts.get(candidate.source, 0) + 1
    for item in diagnostics:
        provider = item["provider"].split(":", 1)[0]
        selected_provider_counts[provider] = selected_provider_counts.get(provider, 0) + 1
    report["candidate_quality"] = {
        "single_candidate_count": sum(count == 1 for count in candidate_counts),
        "double_candidate_count": sum(count == 2 for count in candidate_counts),
        "three_or_more_candidate_count": sum(count >= 3 for count in candidate_counts),
        "hard_candidate_paragraph_count": hard_count,
        "provider_candidate_counts": provider_counts,
        "selected_provider_counts": selected_provider_counts,
        "veto_count": sum(
            bool(candidate.vetoes) for options in candidate_summary.values() for candidate in options
        ),
    }
    summary = RecognitionSummary(
        engine_version=RECOGNITION_ENGINE_VERSION,
        diagnostic_schema_version=RECOGNITION_DIAGNOSTIC_SCHEMA_VERSION,
        document_mode=mode.value,
        block_count=len(blocks),
        paragraph_count=len(diagnostics),
        table_count=sum(block.kind == "table" for block in blocks),
        image_count=sum(block.kind == "image" for block in blocks),
        low_confidence_count=sum(item["review_confidence"] < config.review_low_score for item in diagnostics),
        needs_review_count=sum(item["needs_review"] for item in diagnostics),
        validator_action_count=sum(len(item["validator_actions"]) for item in diagnostics),
        unknown_type_fallback_count=sum(item["final_type"] == ParagraphType.UNKNOWN.value for item in diagnostics),
        candidate_count_total=sum(candidate_counts),
        max_candidate_count=max(candidate_counts, default=0),
        beam_width=config.beam_width,
    )
    report["summary"] = asdict(summary)
    report["summary"].update({
        "confirmed_count": sum(item["review_level"] == "confirmed" for item in diagnostics),
        "info_count": sum(item["review_level"] == "info" for item in diagnostics),
        "review_count": sum(item["review_level"] == "review" for item in diagnostics),
        "critical_review_count": sum(item["review_level"] == "critical_review" for item in diagnostics),
    })
    try:
        from docxtool.document.engine.document_structure import analyze_document_structure
        setattr(data, "recognition_structure", analyze_document_structure(data))
        report["structure_tree"] = "built"
    except (ValueError, TypeError, AttributeError) as exc:
        # Recognition must remain usable for malformed source packages; the
        # validator records the failure instead of hiding it in a warning log.
        report["structure_tree"] = "unavailable"
        report["structure_error"] = type(exc).__name__
    setattr(data, "recognition_diagnostics", report)
