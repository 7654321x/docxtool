"""Legacy-compatible structural scorer selection for imported paragraphs."""

from __future__ import annotations

from typing import Any, Callable, List, Sequence, Tuple

from docxtool.document.recognition.front_matter import (
    legacy_author_line_score,
    legacy_date_line_score,
    legacy_role_name_score,
    legacy_title_cont_score,
    legacy_title_score,
)
from docxtool.document.recognition.numbering import legacy_numbered_heading_score

Scorer = Callable[[str, Any, Any], Tuple[int, dict, str]]
ScorerEntry = Tuple[str, Scorer]
ScorerRegistry = Tuple[List[ScorerEntry], List[ScorerEntry]]


def build_legacy_scorer_registry(
    *,
    match_numbering_func: Callable[[str], Tuple[str, str]],
    contains_colon_func: Callable[[str], bool],
) -> ScorerRegistry:
    """构建旧 importer 的结构 scorer 和正文兜底 scorer。"""

    def score_title(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        tid, _ = match_numbering_func(text)
        score = legacy_title_score(
            text,
            ctx.prev_type_id,
            has_seen_body=ctx.has_seen_body,
            contains_colon=contains_colon_func(text),
            has_numbering=bool(tid),
        )
        return (score, {"is_title": True}, "") if score else (0, {}, "")

    def score_title_cont(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        tid, _ = match_numbering_func(text)
        score = legacy_title_cont_score(
            text,
            ctx.prev_type_id,
            has_seen_body=ctx.has_seen_body,
            contains_colon=contains_colon_func(text),
            has_numbering=bool(tid),
        )
        return (score, {}, "") if score else (0, {}, "")

    def score_date_line(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        tid, _ = match_numbering_func(text)
        score = legacy_date_line_score(
            text,
            ctx.prev_type_id,
            has_seen_body=ctx.has_seen_body,
            has_numbering=bool(tid),
        )
        return (score, {}, "") if score else (0, {}, "")

    def score_author_line(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        tid, _ = match_numbering_func(text)
        score = legacy_author_line_score(
            text,
            ctx.prev_type_id,
            has_seen_body=ctx.has_seen_body,
            contains_colon=contains_colon_func(text),
            has_numbering=bool(tid),
        )
        return (score, {}, "") if score else (0, {}, "")

    def score_role_name(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        if ctx.has_seen_body or ctx.prev_type_id not in (
            "title", "title_cont", "date_line", "author_line"
        ):
            return 0, {}, ""
        prev_title = ctx.title_texts[-1] if ctx.title_texts else ""
        score = legacy_role_name_score(text, prev_title, contains_colon=contains_colon_func(text))
        return (score, {}, "") if score else (0, {}, "")

    def score_heading(text: str, _features: Any, _ctx: Any) -> Tuple[int, dict, str]:
        tid, prefix = match_numbering_func(text)
        score = legacy_numbered_heading_score(
            text,
            tid,
            prefix,
            contains_colon=contains_colon_func(text),
        )
        return (score, {}, prefix) if score else (0, {}, "")

    def score_body_default(_text: str, _features: Any, _ctx: Any) -> Tuple[int, dict, str]:
        return 10, {}, ""

    def heading_scorer(expected: str) -> Scorer:
        def score(text: str, features: Any, ctx: Any) -> Tuple[int, dict, str]:
            result = score_heading(text, features, ctx)
            return result if match_numbering_func(text)[0] == expected else (0, {}, "")

        return score

    structure_scorers: List[ScorerEntry] = [
        ("title", score_title),
        ("title_cont", score_title_cont),
        ("date_line", score_date_line),
        ("author_line", score_author_line),
        ("role_name", score_role_name),
        ("heading1", heading_scorer("heading1")),
        ("heading2", heading_scorer("heading2")),
        ("heading3", heading_scorer("heading3")),
        ("heading4", heading_scorer("heading4")),
    ]
    return structure_scorers, [("body", score_body_default)]


def select_legacy_scored_type(
    text: str,
    features: Any,
    ctx: Any,
    *,
    structure_scorers: Sequence[ScorerEntry],
    fallback_scorers: Sequence[ScorerEntry],
    flow_allows_func: Callable[[str, Any], bool],
) -> Tuple[str, dict, str, List[str]]:
    """按结构 scorer 和正文兜底 scorer 选择旧 importer 段落类型。"""
    type_id = "body"
    meta: dict = {}
    prefix = ""
    best_score = -1
    score_log: List[str] = []

    for candidate, scorer in structure_scorers:
        score, candidate_meta, candidate_prefix = scorer(text, features, ctx)
        if score > 0:
            score_log.append(f"{candidate}:{score}")
        if score > best_score and score > 0 and flow_allows_func(candidate, ctx):
            best_score, type_id, meta, prefix = score, candidate, candidate_meta, candidate_prefix

    if best_score < 0:
        for candidate, scorer in fallback_scorers:
            score, candidate_meta, candidate_prefix = scorer(text, features, ctx)
            if score > best_score and flow_allows_func(candidate, ctx):
                best_score, type_id, meta, prefix = score, candidate, candidate_meta, candidate_prefix

    return type_id, meta, prefix, score_log
