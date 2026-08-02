"""Whole-document beam decoding pipeline."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import math
from typing import Any

from ..candidates import Candidate, DEFAULT_PROVIDERS
from ..compatibility import to_paragraph_type
from ..config import DEFAULT_CONFIG, RecognitionConfig
from ..features import detect_mode, extract_blocks, extract_features
from ..global_context import analyze_document_context
from ..model import DocumentMode, ParagraphType, RecognitionSummary, SectionKind
from ..validators import validate_diagnostics
from ..version import (
    RECOGNITION_DIAGNOSTIC_SCHEMA_VERSION,
    RECOGNITION_ENGINE_VERSION,
    RECOGNITION_VERSION_TAG,
)
from .candidate_selection import _candidates, _limit_candidates, _mode_as_legacy
from .model import _Beam, _Context
from .review import _review_assessment
from .transitions import _hard_veto, _transition


def apply_recognition(
    data: Any,
    config: RecognitionConfig | None = None,
    *,
    providers=DEFAULT_PROVIDERS,
) -> None:
    """Resolve all text blocks using a width-12 beam and preserve diagnostics."""
    config = config or DEFAULT_CONFIG
    blocks = extract_blocks(data)
    execution_mode = config.mode
    paragraph_blocks = [
        block
        for block in blocks
        if block.paragraph_index is not None and block.kind in {"paragraph", "empty", "caption"}
    ]
    boundary_prefix = [0]
    for item in blocks:
        boundary_prefix.append(
            boundary_prefix[-1]
            + int(item.kind in {"table", "image", "page_break", "section_break"})
        )
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
    for pos, (block, features) in enumerate(zip(paragraph_blocks, extracted)):
        previous_features = extracted[pos - 1] if pos else None
        next_beams: list[_Beam] = []
        boundary_start = paragraph_blocks[pos - 1].index + 1 if pos else 0
        boundary_before = boundary_prefix[block.index] > boundary_prefix[boundary_start]
        lookahead = extracted[pos + 1 : pos + 9]
        for beam in beams:
            context = _Context(
                mode, beam.types[-1] if beam.types else None, pos, boundary_before, document_context
            )
            options = tuple(
                _limit_candidates(
                    _candidates(
                        block, features, context, previous_features, lookahead, config, providers
                    ),
                    config,
                )
            )
            hard_types = {item.paragraph_type for item in options if item.hard}
            for candidate in options:
                if hard_types and candidate.paragraph_type not in hard_types:
                    continue
                if _hard_veto(candidate, features, mode, context, block):
                    continue
                section = candidate.section_hint or SectionKind.BODY
                next_beams.append(
                    _Beam(
                        beam.score
                        + candidate.score
                        + _transition(
                            context.previous_type,
                            candidate,
                            beam.sections[-1] if beam.sections else None,
                            mode,
                            boundary_before,
                        ),
                        beam.types + (candidate.paragraph_type,),
                        beam.reasons + (f"{candidate.source}:{','.join(candidate.evidence)}",),
                        beam.sections + (section,),
                        beam.candidate_options + (options,),
                        beam.selected_candidates + (candidate,),
                    )
                )
        if not next_beams:
            # A malformed candidate provider must not make import fail.
            fallback = Candidate(
                ParagraphType.BODY,
                0.0,
                "fallback",
                ("hard-veto",),
                section_hint=SectionKind.BODY,
            )
            next_beams = [
                _Beam(
                    beam.score,
                    beam.types + (ParagraphType.BODY,),
                    beam.reasons + ("fallback:hard-veto",),
                    beam.sections + (SectionKind.BODY,),
                    beam.candidate_options + ((fallback,),),
                    beam.selected_candidates + (fallback,),
                )
                for beam in beams
            ]
        next_beams.sort(
            key=lambda item: (-item.score, tuple(value.value for value in item.types), item.reasons)
        )
        beams = next_beams[: config.beam_width]
    diagnostics = []
    candidate_summary: dict[int, tuple[Candidate, ...]] = {}
    if beams:
        best = beams[0]
        if config.enable_diagnostics:
            for position, (block, features, options) in enumerate(
                zip(paragraph_blocks, extracted, best.candidate_options)
            ):
                boundary_start = paragraph_blocks[position - 1].index + 1 if position else 0
                boundary_before = boundary_prefix[block.index] > boundary_prefix[boundary_start]
                candidate_trace.append(
                    {
                        "paragraph_index": features.paragraph_index,
                        "candidate_count": len(options),
                        "candidates": [
                            {
                                "type": item.paragraph_type.value,
                                "score": item.score,
                                "source": item.source,
                                "hard": item.hard,
                                "evidence": item.evidence,
                                "vetoes": sorted(value.value for value in item.vetoes),
                            }
                            for item in options
                        ],
                        "boundary_before": boundary_before,
                    }
                )
        for position, (block, features, type_value, reason, section) in enumerate(
            zip(paragraph_blocks, extracted, best.types, best.reasons, best.sections)
        ):
            paragraph = getattr(block, "raw_reference", None)
            if paragraph is None:
                continue
            existing_meta = dict(getattr(paragraph, "meta", {}) or {})
            legacy_record = existing_meta.get("legacy_type_id")
            legacy_type_id = (
                legacy_record.get("value") if isinstance(legacy_record, dict) else legacy_record
            ) or paragraph.type_id
            compatible = to_paragraph_type(type_value)
            mapping_failed = compatible is None
            mapping_applied = execution_mode == "authoritative" and not mapping_failed
            if mapping_applied:
                paragraph.type_id = compatible
            final_type_id = paragraph.type_id
            meta = existing_meta
            if not isinstance(meta.get("legacy_type_id"), dict):
                meta["legacy_type_id"] = {
                    "value": legacy_type_id,
                    "source": "observed_input",
                    "recognition_version": RECOGNITION_VERSION_TAG,
                }
            options = (
                best.candidate_options[position] if position < len(best.candidate_options) else ()
            )
            candidate_summary[features.paragraph_index] = tuple(options)
            selected = (
                best.selected_candidates[position]
                if position < len(best.selected_candidates)
                else None
            )
            if selected is not None and selected.paragraph_type != type_value:
                selected = next(
                    (item for item in options if item.paragraph_type == type_value), None
                )
            final_score = selected.score if selected else 0.0
            scores = [item.score for item in options]
            max_score = max(scores, default=0.0)
            weights = [math.exp(score - max_score) for score in scores]
            denominator = sum(weights)
            selected_index = next(
                (index for index, item in enumerate(options) if item.paragraph_type == type_value),
                None,
            )
            local_confidence = (
                weights[selected_index] / denominator
                if selected_index is not None and denominator > 0
                else 0.0
            )
            competing_scores = sorted(
                (item.score for item in options if item.paragraph_type != type_value), reverse=True
            )
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
            review_legacy_type_id = legacy_type_id if config.enable_legacy_candidates else ""
            review_confidence, review_level, review_reasons, evidence_summary = _review_assessment(
                selected,
                features,
                review_legacy_type_id,
                compatible,
                mapping_failed,
                final_score,
                margin,
                config,
                execution_mode,
                document_context.heading_reasons(position),
            )
            meta.update(
                {
                    "recognition_type": type_value.value,
                    "recognized_type": type_value.value,
                    "recognition_section": section.value,
                    "recognition_provider": reason,
                    "recognition_mode": execution_mode,
                    "document_mode": mode.value,
                    "recognition_block_index": block.index,
                    "recognition_paragraph_index": features.paragraph_index,
                    # This remains the raw candidate-distribution diagnostic for
                    # backwards compatibility.  It must not be presented as the
                    # user-facing certainty of the final recognition result.
                    "recognition_confidence": round(local_confidence, 4),
                    "review_confidence": review_confidence,
                    "review_level": review_level,
                    "recognition_evidence": evidence_summary,
                    "review_reasons": review_reasons,
                    "mapping_applied": mapping_applied,
                    "mapping_failed": mapping_failed,
                    "final_type": final_type_id,
                }
            )
            if mode != DocumentMode.REPORT:
                meta.pop("report_first_sentence_bold", None)
            paragraph.meta = meta
            diagnostics.append(
                {
                    "paragraph_index": features.paragraph_index,
                    "block_index": block.index,
                    "text_preview": hashlib.sha256(
                        features.normalized_text.encode("utf-8")
                    ).hexdigest()[: config.text_preview_length],
                    "document_mode": mode.value,
                    "recognition_mode": execution_mode,
                    "result_applied": execution_mode == "authoritative",
                    "state_before": previous_section.value
                    if previous_section
                    else SectionKind.BODY.value,
                    "state_after": section.value,
                    "front_matter": position in document_context.front_positions,
                    "body_start": document_context.body_start == position,
                    "body_start_reason": document_context.body_start_reason
                    if document_context.body_start == position
                    else "",
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
                }
            )
    if execution_mode == "authoritative":
        setattr(data, "doc_mode", _mode_as_legacy(mode))
    report = {
        "engine_version": RECOGNITION_ENGINE_VERSION,
        "schema_version": RECOGNITION_DIAGNOSTIC_SCHEMA_VERSION,
        "config": {
            "mode": execution_mode,
            "beam_width": config.beam_width,
            "max_candidates_per_paragraph": config.max_candidates_per_paragraph,
            "diagnostics": config.enable_diagnostics,
            "review_low_score": config.review_low_score,
            "review_margin": config.review_margin,
        },
        "recognition_mode": execution_mode,
        "result_applied": execution_mode == "authoritative",
        "mode": mode.value,
        "mode_confidence": decision.confidence,
        "mode_evidence": decision.evidence,
        "beam_width": config.beam_width,
        "blocks": [
            {"index": block.index, "kind": block.kind, "paragraph_index": block.paragraph_index}
            for block in blocks
        ],
        "candidate_trace": candidate_trace,
        "paragraphs": diagnostics,
        "document_context": document_context.diagnostic_summary(),
    }
    report["validation"] = validate_diagnostics(report)
    candidate_counts = [item["candidate_count"] for item in diagnostics]
    hard_count = sum(
        any(candidate.hard for candidate in options) for options in candidate_summary.values()
    )
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
            bool(candidate.vetoes)
            for options in candidate_summary.values()
            for candidate in options
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
        low_confidence_count=sum(
            item["review_confidence"] < config.review_low_score for item in diagnostics
        ),
        needs_review_count=sum(item["needs_review"] for item in diagnostics),
        validator_action_count=sum(len(item["validator_actions"]) for item in diagnostics),
        unknown_type_fallback_count=sum(
            item["final_type"] == ParagraphType.UNKNOWN.value for item in diagnostics
        ),
        candidate_count_total=sum(candidate_counts),
        max_candidate_count=max(candidate_counts, default=0),
        beam_width=config.beam_width,
    )
    report["summary"] = asdict(summary)
    report["summary"].update(
        {
            "confirmed_count": sum(item["review_level"] == "confirmed" for item in diagnostics),
            "info_count": sum(item["review_level"] == "info" for item in diagnostics),
            "review_count": sum(item["review_level"] == "review" for item in diagnostics),
            "critical_review_count": sum(
                item["review_level"] == "critical_review" for item in diagnostics
            ),
        }
    )
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
