"""Logical source-span planning for physical-to-logical segmentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from docxtool.document.models import ParagraphFeatures
from docxtool.document.segmentation.source_locator import trim_source_span


@dataclass
class LogicalSpanPlan:
    """保存一个物理段落拆分后的逻辑范围计划。

    传入数据由 `build_logical_span_plan()` 生成。字段返回逻辑 source span、
    是否可保留整段 inline tokens，以及本物理段是否已进入正文区域。
    """

    spans: list[Tuple[int, int]]
    preserve_inline_tokens: bool
    current_body_region: bool


def build_logical_span_plan(
    source: str,
    source_spans: list[Tuple[int, int]],
    *,
    body_region_started: bool,
    has_structural_inline: bool,
    has_page_break: bool,
    structural_preservation: bool,
    split_inline_heading_body_enabled: bool,
    following_text: str,
    features: Optional[ParagraphFeatures],
    source_starts_body_region_func: Callable[[str], bool],
    split_inline_heading_body_spans_func: Callable[..., list[Tuple[int, int]]],
    validate_numbered_heading_body_split_func: Callable[[str, list[Tuple[int, int]], Optional[ParagraphFeatures]], None],
    should_split_structural_line_breaks_func: Callable[[list[str], str], bool],
    split_structural_tail_after_numbered_heading_func: Callable[[str, list[Tuple[int, int]], str], list[Tuple[int, int]]],
    validate_source_span_partition_func: Callable[[str, list[Tuple[int, int]]], None],
) -> LogicalSpanPlan:
    """为一个物理段落生成逻辑 source span 计划。

    传入数据是物理段原文、非空行范围、处理模式开关、下一段文本、段落
    特征和旧识别证据回调。返回值只包含分段范围和 token 保留策略，
    不创建 `ParagraphData`，也不判断最终段落类型。
    """
    source_lines = [source[start:end] for start, end in source_spans]
    whole_start, whole_end = trim_source_span(source, 0, len(source))
    current_body_region = body_region_started or source_starts_body_region_func(source)
    should_split_inline_heading_body = (
        structural_preservation
        and (split_inline_heading_body_enabled or has_page_break)
    )
    whole_heading_spans = (
        split_inline_heading_body_spans_func(
            source,
            whole_start,
            whole_end,
            features,
            allow_visual_boundary=not current_body_region,
        )
        if should_split_inline_heading_body else [(whole_start, whole_end)]
    )
    if should_split_inline_heading_body:
        validate_numbered_heading_body_split_func(source, whole_heading_spans, features)

    split_soft_lines = (
        len(source_spans) > 1
        and should_split_structural_line_breaks_func(source_lines, following_text)
    )
    split_inline_heading = len(whole_heading_spans) > 1
    if split_inline_heading:
        spans = split_structural_tail_after_numbered_heading_func(
            source,
            whole_heading_spans,
            following_text,
        )
        preserve_inline_tokens = False
    elif has_structural_inline and not split_soft_lines:
        spans = [(whole_start, whole_end)]
        preserve_inline_tokens = source[whole_start:whole_end] == source
    else:
        spans = []
        for start, end in source_spans:
            if should_split_inline_heading_body:
                spans.extend(split_inline_heading_body_spans_func(
                    source,
                    start,
                    end,
                    features,
                    allow_visual_boundary=not current_body_region,
                ))
            else:
                spans.append((start, end))
        preserve_inline_tokens = False

    validate_source_span_partition_func(source, spans)
    return LogicalSpanPlan(
        spans=spans,
        preserve_inline_tokens=preserve_inline_tokens,
        current_body_region=current_body_region,
    )
