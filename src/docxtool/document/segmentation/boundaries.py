"""Logical boundary detection for physical-to-logical paragraph splitting."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional, Tuple

from docxtool.document.models import ParagraphFeatures, SegmentBoundaryCandidate
from docxtool.document.segmentation.source_locator import (
    source_line_spans,
    trim_source_span,
    visible_character_count,
)


def has_format_transition(
    features: Optional[ParagraphFeatures],
    start: int,
    boundary: int,
    end: int,
) -> bool:
    """判断候选边界两侧是否存在明显 run 格式切换。

    传入数据是段落特征和源文本中的左右范围。返回值为布尔值，用于支持
    无编号标题与正文粘连时的弱视觉边界证据。
    """
    if not features or not features.source_run_spans:
        return False
    left = []
    right = []
    for run in features.source_run_spans:
        if min(boundary, run.end) > max(start, run.start):
            left.append(run)
        if min(end, run.end) > max(boundary, run.start):
            right.append(run)
    if not left or not right:
        return False
    left_bold = any(run.bold is True for run in left)
    right_bold = any(run.bold is True for run in right)
    if left_bold != right_bold:
        return True
    left_sizes = [run.font_size_pt for run in left if run.font_size_pt is not None]
    right_sizes = [run.font_size_pt for run in right if run.font_size_pt is not None]
    if left_sizes and right_sizes and max(left_sizes) >= max(right_sizes) + 1.0:
        return True
    left_fonts = {run.font_name for run in left if run.font_name}
    right_fonts = {run.font_name for run in right if run.font_name}
    return bool(left_fonts and right_fonts and left_fonts != right_fonts)


def heading_has_inline_body(text: str) -> bool:
    """判断标题文本句号后是否粘连了足够长度的正文。

    传入数据是一段标题候选文本。返回值为布尔值，只表示存在“标题。
    正文”边界事实；不拆分文本，也不决定最终标题层级。
    """
    period_pos = (text or "").find("。")
    return period_pos >= 0 and len((text or "")[period_pos + 1:].strip()) >= 5


def segment_boundary_candidates(
    source: str,
    start: int,
    end: int,
    features: Optional[ParagraphFeatures] = None,
    *,
    analyze_colon_structure_func: Callable[[str], Any],
    detect_numbering_prefix_func: Callable[[str], str],
) -> Tuple[SegmentBoundaryCandidate, ...]:
    """生成一个可见源范围内的逻辑边界候选。

    传入数据是源文本、code-point 范围、段落特征，以及 importer 提供的冒号
    与编号规则回调。返回值是按置信度排序的边界候选，不修改文本。
    """
    start, end = trim_source_span(source, start, end)
    if start >= end:
        return ()
    text = source[start:end]
    candidates = []
    colon = analyze_colon_structure_func(text)
    if colon.inline_addressing_body and colon.separator_index is not None:
        boundary = start + colon.separator_index + 1
        body_start, body_end = trim_source_span(source, boundary, end)
        if body_start < body_end:
            candidates.append(SegmentBoundaryCandidate(
                raw_start=start,
                raw_end=boundary,
                left_type_hint="addressing",
                right_type_hint="body",
                confidence=0.98,
                evidence=("INLINE_ADDRESSING_COLON", "VISIBLE_BODY_AFTER_COLON"),
            ))
    period_index = text.find("。")
    if period_index >= 0:
        boundary = start + period_index + 1
        body_start, body_end = trim_source_span(source, boundary, end)
        left = source[start:boundary]
        body_count = visible_character_count(source[body_start:body_end])
        numbered = bool(detect_numbering_prefix_func(left))
        visual_transition = has_format_transition(features, start, boundary, end)
        if body_count >= 5 and (numbered or visual_transition):
            candidates.append(SegmentBoundaryCandidate(
                raw_start=start,
                raw_end=boundary,
                left_type_hint="heading" if numbered else "title_or_heading",
                right_type_hint="body",
                confidence=0.99 if numbered else 0.84,
                evidence=(
                    "NUMBERED_HEADING_TERMINATOR" if numbered else "VISUAL_TITLE_TERMINATOR",
                    "VISIBLE_BODY_AFTER_TERMINATOR",
                ),
            ))

    return tuple(sorted(candidates, key=lambda item: (-item.confidence, item.raw_end)))


def split_inline_heading_body_spans(
    source: str,
    start: int,
    end: int,
    features: Optional[ParagraphFeatures] = None,
    *,
    allow_visual_boundary: bool = True,
    analyze_colon_structure_func: Callable[[str], Any],
    detect_numbering_prefix_func: Callable[[str], str],
) -> list[Tuple[int, int]]:
    """拆分标题和正文粘连的源范围。

    传入数据是源文本范围、段落特征、视觉边界开关和旧规则回调。返回值是
    逻辑段 source span 列表；编号标题最多拆成“标题 + 一个正文”。
    """
    start, end = trim_source_span(source, start, end)
    if start >= end:
        return []
    root_candidates = segment_boundary_candidates(
        source,
        start,
        end,
        features,
        analyze_colon_structure_func=analyze_colon_structure_func,
        detect_numbering_prefix_func=detect_numbering_prefix_func,
    )
    numbered_heading = next(
        (item for item in root_candidates if item.left_type_hint == "heading"), None
    )
    if numbered_heading is not None:
        body_start, body_end = trim_source_span(source, numbered_heading.raw_end, end)
        if body_start < body_end:
            return [(numbered_heading.raw_start, numbered_heading.raw_end), (body_start, body_end)]
    spans = [(start, end)]
    for _unused in range(2):
        changed = False
        next_spans = []
        for current_start, current_end in spans:
            candidates = segment_boundary_candidates(
                source,
                current_start,
                current_end,
                features,
                analyze_colon_structure_func=analyze_colon_structure_func,
                detect_numbering_prefix_func=detect_numbering_prefix_func,
            )
            if not allow_visual_boundary:
                candidates = tuple(
                    item for item in candidates if item.left_type_hint != "title_or_heading"
                )
            if not candidates:
                next_spans.append((current_start, current_end))
                continue
            candidate = candidates[0]
            right_start, right_end = trim_source_span(source, candidate.raw_end, current_end)
            if candidate.raw_start < candidate.raw_end and right_start < right_end:
                next_spans.extend(((candidate.raw_start, candidate.raw_end), (right_start, right_end)))
                changed = True
            else:
                next_spans.append((current_start, current_end))
        spans = next_spans
        if not changed:
            break
    return spans


def is_strong_soft_line_structure(
    text: str,
    *,
    detect_numbering_prefix_func: Callable[[str], str],
    is_standalone_addressing_func: Callable[[str], bool],
    is_sign_date_func: Callable[[str], bool],
    is_attachment_boundary_func: Callable[[str], bool],
) -> bool:
    """判断软换行后的独立行是否是强结构。

    传入数据是一行文本和 importer 提供的结构判断回调。返回值为布尔值，
    用于决定正文后是否允许继续拆出称呼、日期或附件等结构行。
    """
    value = (text or "").strip()
    return bool(
        value
        and (
            detect_numbering_prefix_func(value)
            or is_standalone_addressing_func(value)
            or is_sign_date_func(value)
            or is_attachment_boundary_func(value)
        )
    )


def split_structural_tail_after_numbered_heading(
    source: str,
    heading_body_spans: list[Tuple[int, int]],
    next_text: str = "",
    *,
    is_strong_soft_line_structure_func: Callable[[str], bool],
    is_sign_date_func: Callable[[str], bool],
    is_tail_signature_org_func: Callable[[str], bool],
) -> list[Tuple[int, int]]:
    """在“编号标题 + 一段正文”之后释放可靠的独立尾部结构。

    传入数据是源文本、已拆出的标题正文范围、下一物理段文本和结构回调。
    返回值是新的 source span 列表；正文自身仍保持为一个完整段。
    """
    if len(heading_body_spans) != 2:
        return heading_body_spans
    heading_span, body_span = heading_body_spans
    body_start, body_end = body_span
    line_spans = source_line_spans(source)
    next_visible_line = next(
        (part.strip() for part in (next_text or "").splitlines() if part.strip()),
        "",
    )
    structural_indexes = []
    for index, (start, end) in enumerate(line_spans):
        if start <= body_start:
            continue
        value = source[start:end]
        if is_strong_soft_line_structure_func(value):
            structural_indexes.append(index)
            continue
        if (
            index + 1 < len(line_spans)
            and is_sign_date_func(source[line_spans[index + 1][0]:line_spans[index + 1][1]])
            and is_tail_signature_org_func(value)
        ):
            structural_indexes.append(index)
            continue
        if (
            index == len(line_spans) - 1
            and is_sign_date_func(next_visible_line)
            and is_tail_signature_org_func(value)
        ):
            structural_indexes.append(index)
    if not structural_indexes:
        return heading_body_spans

    result = [heading_span]
    cursor = body_start
    for index in structural_indexes:
        start, end = line_spans[index]
        preceding = trim_source_span(source, cursor, start)
        if preceding[0] < preceding[1]:
            result.append(preceding)
        result.append((start, end))
        cursor = end
    trailing = trim_source_span(source, cursor, body_end)
    if trailing[0] < trailing[1]:
        result.append(trailing)
    return result


def validate_source_span_partition(source: str, spans: list[Tuple[int, int]]) -> None:
    """校验 source span 是否覆盖所有可见文字且不重叠。

    传入数据是源文本和拆分后的范围列表。函数返回 `None`；发现遗漏、
    重叠或越界时抛出 `ValueError`。
    """
    if not spans:
        return
    previous_end = 0
    for start, end in spans:
        if start < previous_end or start >= end or end > len(source):
            raise ValueError("结构分段范围重叠或越界")
        if re.sub(r"\s+", "", source[previous_end:start]):
            raise ValueError("结构分段遗漏了原始可见文字")
        previous_end = end
    if re.sub(r"\s+", "", source[previous_end:]):
        raise ValueError("结构分段遗漏了原始可见文字")


def source_starts_body_region(
    source: str,
    *,
    detect_numbering_prefix_func: Callable[[str], str],
) -> bool:
    """判断一个物理段是否足以开启正文区域。

    传入数据是源文本和编号检测回调。返回值为布尔值，用于 importer 控制
    软换行视觉拆分范围。
    """
    value = re.sub(r"\s+", "", source or "")
    if not value:
        return False
    if detect_numbering_prefix_func(value):
        return True
    return len(value) >= 34 and any(mark in value for mark in "。！？")


def has_inline_lead_bold_transition(
    source: str,
    start: int,
    end: int,
    features: ParagraphFeatures,
    *,
    detect_numbering_prefix_func: Callable[[str], str],
) -> bool:
    """识别正文段内部“加粗引导句 + 普通正文”的格式过渡。

    传入数据是源文本、范围、段落特征和编号检测回调。返回值为布尔值，
    仅用于恢复正文首句强调，不用于创建新段落。
    """
    text = source[start:end]
    period = text.find("。")
    if period <= 0 or detect_numbering_prefix_func(text):
        return False
    boundary = start + period + 1
    if visible_character_count(source[boundary:end]) < 5:
        return False

    def bold_ratio(range_start: int, range_end: int) -> float:
        """计算一个源范围内显式加粗字符比例。"""
        visible_total = bold_total = 0
        for run in features.source_run_spans:
            overlap_start = max(range_start, run.start)
            overlap_end = min(range_end, run.end)
            if overlap_start >= overlap_end:
                continue
            count = visible_character_count(source[overlap_start:overlap_end])
            visible_total += count
            if run.bold is True:
                bold_total += count
        return bold_total / visible_total if visible_total else 0.0

    return bold_ratio(start, boundary) >= 0.7 and bold_ratio(boundary, end) <= 0.3


def validate_numbered_heading_body_split(
    source: str,
    spans: list[Tuple[int, int]],
    features: Optional[ParagraphFeatures] = None,
    *,
    analyze_colon_structure_func: Callable[[str], Any],
    detect_numbering_prefix_func: Callable[[str], str],
) -> None:
    """校验编号标题行内正文只被拆成标题和一个完整正文段。

    传入数据是源文本、拆分范围、段落特征和旧规则回调。函数返回 `None`；
    如果正文被额外拆碎则抛出 `ValueError`。
    """
    start, end = trim_source_span(source, 0, len(source))
    if start >= end:
        return
    candidates = segment_boundary_candidates(
        source,
        start,
        end,
        features,
        analyze_colon_structure_func=analyze_colon_structure_func,
        detect_numbering_prefix_func=detect_numbering_prefix_func,
    )
    heading = next((item for item in candidates if item.left_type_hint == "heading"), None)
    if heading is None:
        return
    body_start, body_end = trim_source_span(source, heading.raw_end, end)
    if body_start >= body_end:
        return
    expected = [(heading.raw_start, heading.raw_end), (body_start, body_end)]
    if spans != expected:
        raise ValueError(
            "编号标题与行内正文必须仅拆为标题和一个完整正文段"
        )
