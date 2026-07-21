"""Deterministic global resolver for paragraph recognition."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Any

from .candidates import Candidate, CandidateContext, DEFAULT_PROVIDERS
from .compatibility import to_type_id
from .config import DEFAULT_CONFIG, RecognitionConfig
from .features import DocumentBlock, detect_mode, extract_blocks, extract_features
from .model import DocumentMode, ParagraphType, RecognitionSummary, SectionKind
from .validators import validate_diagnostics
from .version import RECOGNITION_DIAGNOSTIC_SCHEMA_VERSION, RECOGNITION_ENGINE_VERSION, RECOGNITION_VERSION_TAG


_EMBEDDED_TITLE_RE = re.compile(r"^.{2,32}(?:规划|方案|办法|规定|报告|意见|要点|决定|通知)$")
_SOURCE_NOTE_RE = re.compile(r"^(?:来源|注|说明|备注)\s*[:：]")
_MEETING_LABELS = frozenset({"时间", "地点", "主持", "记录", "出席", "缺席", "列席", "参会", "参加", "议题", "议定事项", "会议名称", "会议时间", "会议地点"})


@dataclass(frozen=True)
class _Context(CandidateContext):
    mode: DocumentMode
    previous_type: ParagraphType | None
    index: int
    boundary_before: bool = False


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
        result.append(Candidate(ParagraphType.SIGNATURE_DATE, 0.99, "structural", ("date-boundary",), hard=True, section_hint=SectionKind.SIGNATURE))
    if features.recipient_match:
        result.append(Candidate(ParagraphType.RECIPIENT, 0.95, "structural", ("recipient-boundary",), hard=True, section_hint=SectionKind.RECIPIENT))
    has_following_chapter = any(re.match(r"^(?:第[一二三四五六七八九十百0-9]+章|[一二三四五六七八九十]+、)", item.compact_text) for item in lookahead)
    if previous_features and (previous_features.date_match or "本文有删减" in previous_features.compact_text or "本文有删减" in text):
        if _EMBEDDED_TITLE_RE.fullmatch(text):
            score = 0.5
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
    if mode == DocumentMode.MEETING_MINUTES and current.paragraph_type == ParagraphType.MEETING_META:
        return 0.04
    return 0.0


def _hard_veto(candidate: Candidate, features, mode: DocumentMode) -> bool:
    # Structural facts veto visually plausible headings before scoring.
    if features.dispatch_number_match and candidate.paragraph_type != ParagraphType.DISPATCH_NUMBER:
        return True
    if features.date_match and candidate.paragraph_type == ParagraphType.TITLE_CONTINUATION:
        return True
    if features.recipient_match and candidate.paragraph_type == ParagraphType.TITLE_CONTINUATION:
        return True
    if features.key_value_label in _MEETING_LABELS and candidate.paragraph_type in {ParagraphType.HEADING_1, ParagraphType.HEADING_2, ParagraphType.HEADING_3, ParagraphType.HEADING_4}:
        return True
    if mode == DocumentMode.MEETING_MINUTES and features.key_value_label in _MEETING_LABELS and candidate.paragraph_type != ParagraphType.MEETING_META:
        return True
    return False


def apply_recognition(data: Any, config: RecognitionConfig | None = None) -> None:
    """Resolve all text blocks using a width-12 beam and preserve diagnostics."""
    config = config or DEFAULT_CONFIG
    blocks = extract_blocks(data)
    paragraph_blocks = [block for block in blocks if block.paragraph_index is not None and block.kind in {"paragraph", "empty", "image"}]
    boundary_prefix = [0]
    for item in blocks:
        boundary_prefix.append(boundary_prefix[-1] + int(item.kind in {"table", "image", "page_break", "section_break"}))
    extracted = []
    for pos, block in enumerate(paragraph_blocks):
        previous = paragraph_blocks[pos - 1] if pos else None
        following = paragraph_blocks[pos + 1] if pos + 1 < len(paragraph_blocks) else None
        extracted.append(extract_features(block, previous, following))
    decision = detect_mode(extracted, getattr(data, "doc_mode", ""))
    mode = decision.mode
    beams = [_Beam(0.0, (), (), ())]
    candidate_trace: list[dict[str, Any]] = []
    candidate_summary: dict[int, tuple[Candidate, ...]] = {}
    for pos, (block, features) in enumerate(zip(paragraph_blocks, extracted)):
        previous_features = extracted[pos - 1] if pos else None
        next_beams: list[_Beam] = []
        boundary_start = paragraph_blocks[pos - 1].index + 1 if pos else 0
        boundary_before = boundary_prefix[block.index] > boundary_prefix[boundary_start]
        trace_context = _Context(mode, beams[0].types[-1] if beams[0].types else None, pos, boundary_before)
        lookahead = extracted[pos + 1:pos + 9]
        trace_options = _limit_candidates(_candidates(block, features, trace_context, previous_features, lookahead), config)
        candidate_summary[features.paragraph_index] = tuple(trace_options)
        if config.enable_diagnostics:
            candidate_trace.append({"paragraph_index": features.paragraph_index, "candidate_count": len(trace_options), "candidates": [{"type": item.paragraph_type.value, "score": item.score, "source": item.source, "hard": item.hard, "evidence": item.evidence, "vetoes": sorted(value.value for value in item.vetoes)} for item in trace_options], "boundary_before": boundary_before})
        for beam in beams:
            context = _Context(mode, beam.types[-1] if beam.types else None, pos, boundary_before)
            options = _limit_candidates(_candidates(block, features, context, previous_features, lookahead), config)
            for candidate in options:
                if _hard_veto(candidate, features, mode):
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
        for block, features, type_value, reason, section in zip(paragraph_blocks, extracted, best.types, best.reasons, best.sections):
            paragraph = getattr(block, "raw_reference", None)
            if paragraph is None:
                continue
            existing_meta = dict(getattr(paragraph, "meta", {}) or {})
            legacy_record = existing_meta.get("legacy_type_id")
            legacy_type_id = (legacy_record.get("value") if isinstance(legacy_record, dict) else legacy_record) or paragraph.type_id
            compatible = to_type_id(type_value)
            # Every final decision passes through one compatibility mapper.
            # Legacy and core providers still compete as candidates, so this
            # assignment is the sole final type write for text paragraphs.
            # Existing structural/legacy stages still own established types
            # until their providers are migrated one by one. New structural
            # types are written here through the single compatibility exit.
            if type_value in {ParagraphType.DISPATCH_NUMBER, ParagraphType.MEETING_META, ParagraphType.EMBEDDED_DOCUMENT_TITLE, ParagraphType.SOURCE_NOTE}:
                paragraph.type_id = compatible
            meta = existing_meta
            if not isinstance(meta.get("legacy_type_id"), dict):
                meta["legacy_type_id"] = {"value": legacy_type_id, "source": "observed_input", "recognition_version": RECOGNITION_VERSION_TAG}
            meta.update({"recognition_type": type_value.value, "recognition_section": section.value, "recognition_provider": reason, "recognition_mode": mode.value, "recognition_confidence": round(min(1.0, 0.5 + best.score / max(1, len(best.types)) / 2), 3)})
            if mode != DocumentMode.REPORT:
                meta.pop("report_first_sentence_bold", None)
            paragraph.meta = meta
            options = candidate_summary[features.paragraph_index]
            selected = next((item for item in options if item.paragraph_type == type_value), None)
            final_score = selected.score if selected else 0.0
            competing_scores = sorted((item.score for item in options if item.paragraph_type != type_value), reverse=True)
            margin = final_score - competing_scores[0] if competing_scores else None
            review_reasons = []
            if final_score < config.review_low_score:
                review_reasons.append("LOW_FINAL_SCORE")
            if margin is not None and margin < config.review_margin:
                review_reasons.append("SMALL_CANDIDATE_MARGIN")
            if type_value == ParagraphType.UNKNOWN:
                review_reasons.append("UNKNOWN_TYPE_FALLBACK")
            diagnostics.append({"paragraph_index": features.paragraph_index, "block_index": block.index, "text_preview": hashlib.sha256(features.normalized_text.encode("utf-8")).hexdigest()[:config.text_preview_length], "document_mode": mode.value, "state_before": best.sections[max(0, len(best.sections) - len(paragraph_blocks) + len(diagnostics) - 1)].value if best.sections else SectionKind.BODY.value, "state_after": section.value, "candidate_count": len(options), "candidate_types": [item.paragraph_type.value for item in options], "provider": reason, "final_type": type_value.value, "final_score": round(final_score, 4), "candidate_margin": round(margin, 4) if margin is not None else None, "needs_review": bool(review_reasons), "review_reasons": review_reasons, "validator_actions": [], "legacy_type_id": legacy_type_id})
    setattr(data, "doc_mode", _mode_as_legacy(mode))
    report = {"engine_version": RECOGNITION_ENGINE_VERSION, "schema_version": RECOGNITION_DIAGNOSTIC_SCHEMA_VERSION, "config": {"beam_width": config.beam_width, "max_candidates_per_paragraph": config.max_candidates_per_paragraph, "diagnostics": config.enable_diagnostics, "review_low_score": config.review_low_score, "review_margin": config.review_margin}, "mode": mode.value, "mode_confidence": decision.confidence, "mode_evidence": decision.evidence, "beam_width": config.beam_width, "blocks": [{"index": block.index, "kind": block.kind, "paragraph_index": block.paragraph_index} for block in blocks], "candidate_trace": candidate_trace, "paragraphs": diagnostics}
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
        low_confidence_count=sum(item["final_score"] < config.review_low_score for item in diagnostics),
        needs_review_count=sum(item["needs_review"] for item in diagnostics),
        validator_action_count=sum(len(item["validator_actions"]) for item in diagnostics),
        unknown_type_fallback_count=sum(item["final_type"] == ParagraphType.UNKNOWN.value for item in diagnostics),
        candidate_count_total=sum(candidate_counts),
        max_candidate_count=max(candidate_counts, default=0),
        beam_width=config.beam_width,
    )
    report["summary"] = asdict(summary)
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
