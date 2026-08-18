from __future__ import annotations

import importlib
from typing import Optional, Tuple

import docxtool.document.segmentation.pipeline as pipeline_module
from docxtool.document.models import ParagraphFeatures
from docxtool.document.segmentation.body_tail import find_last_body_candidate_index
from docxtool.document.segmentation.pipeline import build_logical_lines, build_logical_span_plan


def _identity_split(
    source: str,
    start: int,
    end: int,
    features: Optional[ParagraphFeatures] = None,
    *,
    document_mode=None,
    allow_visual_boundary: bool = True,
) -> list[Tuple[int, int]]:
    """测试辅助：传入源范围，返回未拆分的原范围。"""
    return [(start, end)]


def _noop_validate(
    source: str,
    spans: list[Tuple[int, int]],
    features: Optional[ParagraphFeatures] = None,
    *,
    document_mode=None,
) -> None:
    """测试辅助：传入源文本和范围，不做额外校验并返回 None。"""
    return None


def test_pipeline_preserves_inline_tokens_when_structural_markers_do_not_split() -> None:
    """结构 token 未形成独立边界时，pipeline 应返回整段范围并允许保留 tokens。"""
    source = "正文\t内容"

    plan = build_logical_span_plan(
        source,
        [(0, len(source))],
        body_region_started=False,
        has_structural_inline=True,
        has_page_break=False,
        structural_preservation=True,
        split_inline_heading_body_enabled=False,
        following_text="",
        features=ParagraphFeatures(source_physical_text=source),
        source_starts_body_region_func=lambda text: False,
        split_inline_heading_body_spans_func=_identity_split,
        validate_numbered_heading_body_split_func=_noop_validate,
        should_split_structural_line_breaks_func=lambda parts, next_text: False,
        split_structural_tail_after_numbered_heading_func=lambda text, spans, next_text: spans,
        validate_source_span_partition_func=lambda text, spans: None,
    )

    assert plan.spans == [(0, len(source))]
    assert plan.preserve_inline_tokens is True
    assert plan.current_body_region is False


def test_pipeline_uses_heading_body_split_and_suppresses_inline_token_preservation() -> None:
    """编号标题拆分成立时，pipeline 应返回拆分范围并禁止保留整段 tokens。"""
    source = "一、标题。正文内容"
    heading_end = source.index("。") + 1

    def split_heading_body(
        text: str,
        start: int,
        end: int,
        features: Optional[ParagraphFeatures] = None,
        *,
        document_mode=None,
        allow_visual_boundary: bool = True,
    ) -> list[Tuple[int, int]]:
        """测试辅助：传入源范围，返回标题和正文两个范围。"""
        return [(start, heading_end), (heading_end, end)]

    plan = build_logical_span_plan(
        source,
        [(0, len(source))],
        body_region_started=False,
        has_structural_inline=False,
        has_page_break=False,
        structural_preservation=True,
        split_inline_heading_body_enabled=True,
        following_text="",
        features=ParagraphFeatures(source_physical_text=source),
        source_starts_body_region_func=lambda text: True,
        split_inline_heading_body_spans_func=split_heading_body,
        validate_numbered_heading_body_split_func=_noop_validate,
        should_split_structural_line_breaks_func=lambda parts, next_text: False,
        split_structural_tail_after_numbered_heading_func=lambda text, spans, next_text: spans,
        validate_source_span_partition_func=lambda text, spans: None,
    )

    assert plan.spans == [(0, heading_end), (heading_end, len(source))]
    assert plan.preserve_inline_tokens is False
    assert plan.current_body_region is True


def test_body_tail_boundary_ignores_signature_and_attachment_lines() -> None:
    """尾部边界扫描应跳过附件、日期和附件页标记，只返回最后正文行。"""
    lines = [
        "一、总体要求。",
        "正文内容。",
        "附件：1.材料",
        "1.测试附件",
        "2026年5月1日",
        "附件1",
    ]

    index = find_last_body_candidate_index(
        lines,
        is_attachment_start_func=lambda text: text.startswith("附件"),
        is_sign_date_func=lambda text: text.endswith("日"),
        is_attachment_item_func=lambda text: text[:1].isdigit() and "." in text[:3],
        is_attachment_page_mark_func=lambda text: text.startswith("附件") and text[2:].isdigit(),
    )

    assert index == 1


def test_pipeline_span_plan_facade_calls_partition_module(monkeypatch) -> None:
    """旧 pipeline 入口应转发到新的 source span 分区模块。"""
    partition_module = importlib.import_module(
        "docxtool.document.segmentation.partition"
    )
    sentinel = partition_module.LogicalSpanPlan(
        spans=[(0, 2)],
        preserve_inline_tokens=True,
        current_body_region=False,
    )
    calls = []

    def fake_build(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(partition_module, "build_logical_span_plan", fake_build)

    result = pipeline_module.build_logical_span_plan(
        "正文",
        [(0, 2)],
        body_region_started=False,
        has_structural_inline=False,
        has_page_break=False,
        structural_preservation=True,
        split_inline_heading_body_enabled=False,
        following_text="",
        features=ParagraphFeatures(source_physical_text="正文"),
        source_starts_body_region_func=lambda text: False,
        split_inline_heading_body_spans_func=_identity_split,
        validate_numbered_heading_body_split_func=_noop_validate,
        should_split_structural_line_breaks_func=lambda parts, next_text: False,
        split_structural_tail_after_numbered_heading_func=lambda text, spans, next_text: spans,
        validate_source_span_partition_func=lambda text, spans: None,
    )

    assert result is sentinel
    assert len(calls) == 1


def test_logical_line_builder_keeps_pipeline_span_plan_monkeypatch(monkeypatch) -> None:
    """旧 pipeline 计划入口被 patch 后，真实 logical-line 构建仍使用该替身。"""
    source = "正文"
    features = ParagraphFeatures(
        text=source,
        source_physical_text=source,
        source_physical_paragraph_index=0,
    )
    calls = []

    def fake_plan(*args, **kwargs):
        calls.append((args, kwargs))
        return pipeline_module.LogicalSpanPlan(
            spans=[(0, len(source))],
            preserve_inline_tokens=False,
            current_body_region=True,
        )

    monkeypatch.setattr(pipeline_module, "build_logical_span_plan", fake_plan)

    lines = build_logical_lines(
        [("paragraph", object(), features, [], None)],
        strict_preservation=False,
        structural_preservation=True,
        split_inline_heading_body_enabled=True,
        normalize_text_func=lambda text: text,
        source_starts_body_region_func=lambda text: False,
        split_inline_heading_body_spans_func=_identity_split,
        validate_numbered_heading_body_split_func=_noop_validate,
        should_split_structural_line_breaks_func=lambda parts, next_text: False,
        split_structural_tail_after_numbered_heading_func=lambda text, spans, next_text: spans,
        validate_source_span_partition_func=lambda text, spans: None,
        detect_numbering_prefix_func=lambda text: "",
        inline_lead_bold_func=lambda source, start, end, features: False,
    )

    assert len(calls) == 1
    assert [(item[0], item[1]) for item in lines] == [("text", source)]
