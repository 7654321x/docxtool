"""Logical source-span planning for physical-to-logical segmentation."""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from docxtool.document.importing.inline_tokens import inline_tokens_text
from docxtool.document.models import ParagraphFeatures
from docxtool.document.segmentation import partition as partition_module
from docxtool.document.segmentation.source_locator import (
    assign_segment_ordinals,
    build_segment_features,
    build_unresolved_empty_segment_features,
    source_line_spans,
)


LogicalSpanPlan = partition_module.LogicalSpanPlan


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
    """兼容旧入口，转发 source span 与 token 保留计划构建。"""
    return partition_module.build_logical_span_plan(
        source,
        source_spans,
        body_region_started=body_region_started,
        has_structural_inline=has_structural_inline,
        has_page_break=has_page_break,
        structural_preservation=structural_preservation,
        split_inline_heading_body_enabled=split_inline_heading_body_enabled,
        following_text=following_text,
        features=features,
        source_starts_body_region_func=source_starts_body_region_func,
        split_inline_heading_body_spans_func=split_inline_heading_body_spans_func,
        validate_numbered_heading_body_split_func=(
            validate_numbered_heading_body_split_func
        ),
        should_split_structural_line_breaks_func=(
            should_split_structural_line_breaks_func
        ),
        split_structural_tail_after_numbered_heading_func=(
            split_structural_tail_after_numbered_heading_func
        ),
        validate_source_span_partition_func=validate_source_span_partition_func,
    )


def build_logical_lines(
    raw_blocks: List[tuple],
    *,
    strict_preservation: bool,
    structural_preservation: bool,
    split_inline_heading_body_enabled: bool,
    normalize_text_func: Callable[[str], str],
    source_starts_body_region_func: Callable[[str], bool],
    split_inline_heading_body_spans_func: Callable[..., list[Tuple[int, int]]],
    validate_numbered_heading_body_split_func: Callable[[str, list[Tuple[int, int]], Optional[ParagraphFeatures]], None],
    should_split_structural_line_breaks_func: Callable[[list[str], str], bool],
    split_structural_tail_after_numbered_heading_func: Callable[[str, list[Tuple[int, int]], str], list[Tuple[int, int]]],
    validate_source_span_partition_func: Callable[[str, list[Tuple[int, int]]], None],
    detect_numbering_prefix_func: Callable[[str], str],
    inline_lead_bold_func: Callable[[str, int, int, ParagraphFeatures], bool],
) -> List[tuple]:
    """将物理 body 块原样转换为逻辑行元组。

    传入 Reader 生成的物理块、既有处理模式开关和当前请求对应的文本规范化
    回调。返回的 tuple 布局、遍历顺序、source span 与 inline token 保留策略
    均与原 ``DocxImporter.load()`` 一致。本函数只划定逻辑边界，不进行段落
    分类、状态迁移、尾部整理或文字重排。
    """
    flat_lines: List[tuple] = []
    body_region_started = False
    for block_index, block in enumerate(raw_blocks):
        if block[0] != "paragraph":
            flat_lines.append(block)
            continue
        _, paragraph, paragraph_features, inline_tokens, sect_pr = block
        source = paragraph_features.source_physical_text
        spans_from_lines = source_line_spans(source)
        has_structural_inline = any(
            token.kind in {"tab", "line_break", "page_break"}
            for token in inline_tokens
        )
        has_page_break = any(token.kind == "page_break" for token in inline_tokens)

        if strict_preservation:
            raw_text = inline_tokens_text(inline_tokens) if inline_tokens else source
            flat_lines.append(("text", raw_text, paragraph_features, list(inline_tokens), sect_pr))
            continue

        if not spans_from_lines:
            if sect_pr is not None or has_page_break:
                sub_features = build_unresolved_empty_segment_features(
                    paragraph_features,
                    paragraph_index=len(flat_lines),
                )
                flat_lines.append(("text", "", sub_features, [], sect_pr))
            continue

        following_text = ""
        for following in raw_blocks[block_index + 1:]:
            if following[0] == "paragraph":
                following_text = normalize_text_func(following[1].text).strip()
                if following_text:
                    break

        span_plan = build_logical_span_plan(
            source,
            spans_from_lines,
            body_region_started=body_region_started,
            has_structural_inline=has_structural_inline,
            has_page_break=has_page_break,
            structural_preservation=structural_preservation,
            split_inline_heading_body_enabled=split_inline_heading_body_enabled,
            following_text=following_text,
            features=paragraph_features,
            source_starts_body_region_func=source_starts_body_region_func,
            split_inline_heading_body_spans_func=split_inline_heading_body_spans_func,
            validate_numbered_heading_body_split_func=(
                validate_numbered_heading_body_split_func
            ),
            should_split_structural_line_breaks_func=(
                should_split_structural_line_breaks_func
            ),
            split_structural_tail_after_numbered_heading_func=(
                split_structural_tail_after_numbered_heading_func
            ),
            validate_source_span_partition_func=validate_source_span_partition_func,
        )
        spans = span_plan.spans
        preserve_tokens = list(inline_tokens) if span_plan.preserve_inline_tokens else []

        for line_index, (start, end) in enumerate(spans):
            raw_fragment = source[start:end]
            line = normalize_text_func(raw_fragment)
            if not line:
                continue
            sub_features = build_segment_features(
                paragraph_features,
                start,
                end,
                paragraph_index=len(flat_lines),
                is_new_line=line_index > 0,
                inline_lead_bold_func=inline_lead_bold_func,
            )
            sub_features.numbering_prefix = (
                paragraph_features.numbering_prefix
                if line_index == 0
                else detect_numbering_prefix_func(line)
            )
            sub_features.segment_numbering_features = sub_features.numbering_prefix
            flat_lines.append((
                "text",
                line,
                sub_features,
                preserve_tokens if len(spans) == 1 else [],
                sect_pr if line_index == len(spans) - 1 else None,
            ))
        body_region_started = span_plan.current_body_region

    assign_segment_ordinals(
        item[2] for item in flat_lines if item[0] == "text"
    )
    return flat_lines
