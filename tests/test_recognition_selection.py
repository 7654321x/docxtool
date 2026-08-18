from __future__ import annotations

from types import SimpleNamespace

from docxtool.document.recognition.selection import (
    build_legacy_scorer_registry,
    select_legacy_scored_type,
)


def _scorer(score: int, meta: dict | None = None, prefix: str = ""):
    """测试辅助：传入固定分值、meta 和前缀，返回旧 scorer 兼容函数。"""
    def score_func(_text, _features, _ctx):
        """测试辅助 scorer：传入旧 scorer 参数，返回固定评分三元组。"""
        return score, dict(meta or {}), prefix

    return score_func


def test_select_legacy_scored_type_prefers_allowed_highest_structure_score() -> None:
    """选择器接收结构 scorer 列表，返回 Flow 允许的最高分候选。"""
    type_id, meta, prefix, score_log = select_legacy_scored_type(
        "测试",
        None,
        SimpleNamespace(doc_mode=""),
        structure_scorers=[
            ("title", _scorer(90, {"title": True})),
            ("heading1", _scorer(100, {"heading": True}, "一、")),
        ],
        fallback_scorers=[("body", _scorer(10))],
        flow_allows_func=lambda candidate, _ctx: candidate != "heading1",
    )

    assert type_id == "title"
    assert meta == {"title": True}
    assert prefix == ""
    assert score_log == ["title:90", "heading1:100"]


def test_select_legacy_scored_type_runs_fallback_only_without_positive_score() -> None:
    """选择器接收无正分 scorer 时，返回兜底层候选。"""
    type_id, meta, prefix, score_log = select_legacy_scored_type(
        "测试",
        None,
        SimpleNamespace(doc_mode=""),
        structure_scorers=[("title", _scorer(0))],
        fallback_scorers=[("body", _scorer(10, {"fallback": True}))],
        flow_allows_func=lambda _candidate, _ctx: True,
    )

    assert type_id == "body"
    assert meta == {"fallback": True}
    assert prefix == ""
    assert score_log == []


def test_build_legacy_scorer_registry_keeps_title_role_and_heading_scores() -> None:
    """旧 scorer registry 接收基础回调，返回可直接用于 importer 的三层评分表。"""
    structure_scorers, fallback_scorers = build_legacy_scorer_registry(
        match_numbering_func=lambda text: ("heading1", "一、") if text.startswith("一、") else ("", ""),
        contains_colon_func=lambda text: "：" in text or ":" in text,
    )

    title_type, title_meta, _, _ = select_legacy_scored_type(
        "关于测试工作的报告",
        None,
        SimpleNamespace(
            prev_type_id=None,
            has_seen_body=False,
            has_seen_real_body=False,
            title_texts=[],
            glossary_mode=False,
        ),
        structure_scorers=structure_scorers,
        fallback_scorers=fallback_scorers,
        flow_allows_func=lambda _candidate, _ctx: True,
    )
    assert title_type == "title"
    assert title_meta == {"is_title": True}

    role_type, _, _, _ = select_legacy_scored_type(
        "办公室主任  张三",
        None,
        SimpleNamespace(
            prev_type_id="title",
            has_seen_body=False,
            has_seen_real_body=False,
            title_texts=["在测试会议上的讲话"],
            glossary_mode=False,
        ),
        structure_scorers=structure_scorers,
        fallback_scorers=fallback_scorers,
        flow_allows_func=lambda _candidate, _ctx: True,
    )
    assert role_type == "role_name"

    heading_type, _, heading_prefix, _ = select_legacy_scored_type(
        "一、提高认识",
        None,
        SimpleNamespace(
            prev_type_id="body",
            has_seen_body=True,
            has_seen_real_body=True,
            title_texts=["关于测试工作的报告"],
            glossary_mode=False,
        ),
        structure_scorers=structure_scorers,
        fallback_scorers=fallback_scorers,
        flow_allows_func=lambda _candidate, _ctx: True,
    )
    assert heading_type == "heading1"
    assert heading_prefix == "一、"
