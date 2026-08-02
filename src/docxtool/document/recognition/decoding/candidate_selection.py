"""Candidate collection and deterministic local ordering."""

from __future__ import annotations

import re

from ..candidates import Candidate, DEFAULT_PROVIDERS
from ..config import RecognitionConfig
from ..features import DocumentBlock
from ..model import DocumentMode, ParagraphType, SectionKind
from .model import _Context


_EMBEDDED_TITLE_RE = re.compile(r"^.{2,32}(?:规划|方案|办法|规定|报告|意见|要点|决定|通知)$")
_SOURCE_NOTE_RE = re.compile(r"^(?:来源|注|说明|备注)\s*[:：]")
_MEETING_LABELS = frozenset(
    {
        "时间",
        "地点",
        "主持",
        "记录",
        "出席",
        "缺席",
        "列席",
        "参会",
        "参加",
        "议题",
        "议定事项",
        "会议名称",
        "会议时间",
        "会议地点",
    }
)


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
    return {
        DocumentMode.REPORT: "REPORT",
        DocumentMode.NORMAL: "NORMAL",
        DocumentMode.UNKNOWN: "UNKNOWN",
    }.get(mode, mode.value.upper())


def _extra_candidates(
    block: DocumentBlock, features, context: _Context, previous_features, lookahead=()
) -> list[Candidate]:
    result: list[Candidate] = []
    text = features.compact_text
    if features.source_note_match:
        result.append(
            Candidate(
                ParagraphType.SOURCE_NOTE,
                0.97,
                "structural",
                ("source-note",),
                hard=True,
                section_hint=SectionKind.SOURCE_NOTE,
            )
        )
    signature_date_evidence = (
        context.document_context.signature_date_reasons(context.index)
        if context.document_context is not None
        else ()
    )
    if signature_date_evidence:
        result.append(
            Candidate(
                ParagraphType.SIGNATURE_DATE,
                0.97,
                "structural",
                signature_date_evidence,
                hard=True,
                section_hint=SectionKind.SIGNATURE,
            )
        )
    has_following_chapter = any(
        re.match(
            r"^(?:第[一二三四五六七八九十百0-9]+章|[一二三四五六七八九十]+、)", item.compact_text
        )
        for item in lookahead
    )
    if previous_features and (
        previous_features.date_match
        or "本文有删减" in previous_features.compact_text
        or "本文有删减" in text
    ):
        if _EMBEDDED_TITLE_RE.fullmatch(text):
            score = 0.86 if has_following_chapter else 0.5
            result.append(
                Candidate(
                    ParagraphType.EMBEDDED_DOCUMENT_TITLE,
                    score,
                    "embedded-document",
                    (
                        "after-signature-or-source-note",
                        "following-chapter" if has_following_chapter else "no-following-chapter",
                    ),
                    hard=False,
                    section_hint=SectionKind.EMBEDDED_DOCUMENT,
                )
            )
    if context.mode == DocumentMode.MEETING_MINUTES and features.key_value_label in _MEETING_LABELS:
        result.append(
            Candidate(
                ParagraphType.MEETING_META,
                1.0,
                "meeting",
                ("meeting-metadata",),
                hard=True,
                section_hint=SectionKind.MEETING_META,
            )
        )
    return result


def _provider_enabled(provider, config: RecognitionConfig) -> bool:
    if provider.name == "core":
        return config.enable_core_candidates
    if provider.name == "legacy":
        return config.enable_legacy_candidates
    return True


def _candidates(
    block: DocumentBlock,
    features,
    context: _Context,
    previous_features,
    lookahead=(),
    config: RecognitionConfig | None = None,
    providers=DEFAULT_PROVIDERS,
) -> list[Candidate]:
    result: list[Candidate] = []
    for provider in providers:
        if config is not None and not _provider_enabled(provider, config):
            continue
        proposed = provider.propose(block, features, context)
        if config is not None and provider.name == "legacy":
            proposed = [
                Candidate(
                    candidate.paragraph_type,
                    min(candidate.score, config.legacy_score),
                    candidate.source,
                    candidate.evidence,
                    candidate.vetoes,
                    candidate.hard,
                    candidate.section_hint,
                    candidate.heading_level,
                )
                for candidate in proposed
            ]
        result.extend(proposed)
    result.extend(_extra_candidates(block, features, context, previous_features, lookahead))
    # One provider may emit the same type more than once. Keep its strongest,
    # deterministic candidate and retain the evidence from the strongest source.
    strongest: dict[ParagraphType, Candidate] = {}
    for candidate in result:
        old = strongest.get(candidate.paragraph_type)
        if old is None or (candidate.hard, candidate.score, candidate.source) > (
            old.hard,
            old.score,
            old.source,
        ):
            strongest[candidate.paragraph_type] = candidate
    if not strongest:
        strongest[ParagraphType.BODY] = Candidate(
            ParagraphType.BODY, 0.5, "fallback", ("no-candidate",), section_hint=SectionKind.BODY
        )
    return sorted(
        strongest.values(), key=lambda item: (-item.hard, -item.score, item.paragraph_type.value)
    )


def _limit_candidates(options: list[Candidate], config: RecognitionConfig) -> list[Candidate]:
    hard = [item for item in options if item.hard]
    soft = [item for item in options if not item.hard]
    return hard + soft[: max(0, config.max_candidates_per_paragraph - len(hard))]
