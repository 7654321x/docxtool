"""Legacy-compatible scorer selection for imported paragraphs."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Sequence, Tuple

from docxtool.document.recognition.document_mode import (
    legacy_heading_addressing_score,
)
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
ScorerRegistry = Tuple[List[ScorerEntry], Dict[str, List[ScorerEntry]], List[ScorerEntry]]


def build_legacy_scorer_registry(
    *,
    match_numbering_func: Callable[[str], Tuple[str, str]],
    contains_colon_func: Callable[[str], bool],
) -> ScorerRegistry:
    """构建旧 importer scorer 表。

    传入编号检测、冒号检测和文种检测回调，返回结构 scorer、文种
    scorer 和兜底 scorer 三张表；只封装候选评分，不推进上下文。
    """

    def score_title(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        """传入段落文本、特征和上下文，返回主标题候选评分。"""
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
        """传入段落文本、特征和上下文，返回标题续行候选评分。"""
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
        """传入段落文本、特征和上下文，返回文首日期行候选评分。"""
        tid, _ = match_numbering_func(text)
        score = legacy_date_line_score(
            text,
            ctx.prev_type_id,
            has_seen_body=ctx.has_seen_body,
            has_numbering=bool(tid),
        )
        return (score, {}, "") if score else (0, {}, "")

    def score_author_line(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        """传入段落文本、特征和上下文，返回文首署名行候选评分。"""
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
        """传入段落文本、特征和上下文，返回职务姓名行候选评分。"""
        if ctx.has_seen_body:
            return 0, {}, ""
        if ctx.prev_type_id not in ("title", "title_cont", "date_line", "author_line"):
            return 0, {}, ""
        prev_title = ctx.title_texts[-1] if ctx.title_texts else ""
        score = legacy_role_name_score(text, prev_title, contains_colon=contains_colon_func(text))
        return (score, {}, "") if score else (0, {}, "")

    def score_heading1(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        """传入段落文本、特征和上下文，返回一级标题候选评分。"""
        tid, prefix = match_numbering_func(text)
        score = legacy_numbered_heading_score(
            text,
            tid,
            prefix,
            contains_colon=contains_colon_func(text),
        )
        return (score, {}, prefix) if score and tid == "heading1" else (0, {}, "")

    def score_heading2(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        """传入段落文本、特征和上下文，返回二级标题候选评分。"""
        tid, prefix = match_numbering_func(text)
        score = legacy_numbered_heading_score(
            text,
            tid,
            prefix,
            contains_colon=contains_colon_func(text),
        )
        return (score, {}, prefix) if score and tid == "heading2" else (0, {}, "")

    def score_heading3(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        """传入段落文本、特征和上下文，返回三级标题候选评分。"""
        tid, prefix = match_numbering_func(text)
        score = legacy_numbered_heading_score(
            text,
            tid,
            prefix,
            contains_colon=contains_colon_func(text),
        )
        return (score, {}, prefix) if score and tid == "heading3" else (0, {}, "")

    def score_heading4(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        """传入段落文本、特征和上下文，返回四级标题候选评分。"""
        tid, prefix = match_numbering_func(text)
        score = legacy_numbered_heading_score(
            text,
            tid,
            prefix,
            contains_colon=contains_colon_func(text),
        )
        return (score, {}, prefix) if score and tid == "heading4" else (0, {}, "")

    def score_title2(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        """传入正文上下文和文本形态，返回通用正文小标题候选评分。"""
        value = text or ""
        tid, _ = match_numbering_func(text)
        score = 95 if (
            (ctx.has_seen_body or ctx.prev_type_id in ("heading1", "heading2", "heading3", "heading4"))
            and len(value) < 28
            and not contains_colon_func(value)
            and not bool(tid)
            and ctx.prev_type_id != "date_line"
            and "。" not in value
        ) else 0
        return (score, {}, "") if score else (0, {}, "")

    def score_glossary_title(text: str, features: Any, ctx: Any) -> Tuple[int, dict, str]:
        """传入段落文本、特征和上下文，返回名词解释标题候选评分。"""
        score, meta, prefix = score_title2(text, features, ctx)
        if score and ("名词解释" in (text or "") or "注释" in (text or "")):
            return score, meta, prefix
        return 0, {}, ""

    def score_glossary_item(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        """传入段落文本、特征和上下文，返回名词解释条目候选评分。"""
        tid, prefix = match_numbering_func(text)
        value = text or ""
        if not ctx.glossary_mode:
            return 0, {}, ""
        body = value[len(prefix):].lstrip() if tid == "heading3" and prefix else value
        if tid != "heading3" and (not contains_colon_func(value) or len(value) < 4):
            return 0, {}, ""
        colon_pos = next((body.find(mark) for mark in ("：", ":") if body.find(mark) > 0), -1)
        return 90, {"glossary_item": True, "colon_pos": colon_pos}, prefix if tid == "heading3" else ""

    def score_heading_addressing(text: str, _features: Any, ctx: Any) -> Tuple[int, dict, str]:
        """传入段落文本、特征和上下文，返回标题后主送机关候选评分。"""
        score = legacy_heading_addressing_score(
            text,
            ctx.prev_type_id,
            has_seen_real_body=ctx.has_seen_real_body,
        )
        return (score, {"no_indent": True}, "") if score else (0, {}, "")

    def score_body_default(_text: str, _features: Any, _ctx: Any) -> Tuple[int, dict, str]:
        """传入段落文本、特征和上下文，返回正文兜底评分。"""
        return 10, {}, ""

    structure_scorers: List[ScorerEntry] = [
        ("title", score_title),
        ("title_cont", score_title_cont),
        ("date_line", score_date_line),
        ("author_line", score_author_line),
        ("role_name", score_role_name),
        ("heading1", score_heading1),
        ("heading2", score_heading2),
        ("heading3", score_heading3),
        ("heading4", score_heading4),
    ]
    mode_scorers: Dict[str, List[ScorerEntry]] = {
        "NORMAL": [
            ("addressing", score_heading_addressing),
            ("glossary_title", score_glossary_title),
            ("title2", score_title2),
            ("glossary_item", score_glossary_item),
        ],
    }
    fallback_scorers: List[ScorerEntry] = [
        ("body", score_body_default),
    ]
    return structure_scorers, mode_scorers, fallback_scorers


def select_legacy_scored_type(
    text: str,
    features: Any,
    ctx: Any,
    *,
    structure_scorers: Sequence[ScorerEntry],
    mode_scorers: Mapping[str, Sequence[ScorerEntry]],
    fallback_scorers: Sequence[ScorerEntry],
    flow_allows_func: Callable[[str, Any], bool],
) -> Tuple[str, dict, str, List[str]]:
    """按旧 importer 三阶段 scorer 选择段落类型。

    传入段落文本、段落特征、旧上下文、骨架 scorer、文种 scorer、兜底
    scorer 和 Flow 判断回调。返回最终候选类型、meta、
    编号前缀和用于日志的得分摘要；不执行 Repair、不推进上下文。
    """
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

    mode = ctx.doc_mode
    if mode:
        for candidate, scorer in mode_scorers.get(mode, ()):
            score, candidate_meta, candidate_prefix = scorer(text, features, ctx)
            if score > best_score and score > 0 and flow_allows_func(candidate, ctx):
                best_score, type_id, meta, prefix = score, candidate, candidate_meta, candidate_prefix

    if best_score < 0:
        for candidate, scorer in fallback_scorers:
            score, candidate_meta, candidate_prefix = scorer(text, features, ctx)
            if score > best_score and flow_allows_func(candidate, ctx):
                best_score, type_id, meta, prefix = score, candidate, candidate_meta, candidate_prefix

    return type_id, meta, prefix, score_log
