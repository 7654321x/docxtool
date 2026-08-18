"""Logical boundary detection for physical-to-logical paragraph splitting."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional, Tuple

from docxtool.document.models import ParagraphFeatures, SegmentBoundaryCandidate
from docxtool.document.recognition.model import DocumentMode
from docxtool.document.segmentation import conservation as conservation_module
from docxtool.document.segmentation.source_locator import (
    source_line_spans,
    trim_source_span,
    visible_character_count,
)


_ANNUAL_REVIEW_HEADING_PREFIXES = ("一年来", "五年来")


def _is_annual_review_inline_heading(text: str, period_index: int, body_count: int) -> bool:
    """Return whether a narrow annual-review lead is a heading/body boundary."""
    heading = text[:period_index].strip()
    return (
        heading in _ANNUAL_REVIEW_HEADING_PREFIXES
        and 0 < period_index <= 50
        and body_count >= 5
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


def _is_heading2_inline_body(
    text: str,
    features: Optional[ParagraphFeatures],
    *,
    detect_numbering_prefix_func: Callable[[str], str],
) -> bool:
    """Return whether one physical paragraph is an explicit heading-2 plus body."""
    if not heading_has_inline_body(text):
        return False
    prefix = detect_numbering_prefix_func(text)
    if re.fullmatch(r"[（(][一二三四五六七八九十百]+[）)]", prefix or ""):
        return True
    source_prefix = str(getattr(features, "numbering_prefix", "") or "")
    if source_prefix == "@style_heading2":
        return True
    native = getattr(features, "native_numbering", None)
    if native is None:
        return False
    template = re.sub(r"\s+", "", str(getattr(native, "lvl_text", "") or ""))
    placeholder = f"%{int(getattr(native, 'ilvl', 0)) + 1}"
    return bool(
        str(getattr(native, "num_fmt", "") or "")
        in {"chineseCounting", "chineseCountingThousand", "ideographTraditional"}
        and re.fullmatch(rf"[（(]{re.escape(placeholder)}[）)]", template)
    )


def segment_boundary_candidates(
    source: str,
    start: int,
    end: int,
    features: Optional[ParagraphFeatures] = None,
    *,
    document_mode: DocumentMode = DocumentMode.UNKNOWN,
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
    if period_index >= 0 and not _is_heading2_inline_body(
        text,
        features,
        detect_numbering_prefix_func=detect_numbering_prefix_func,
    ):
        boundary = start + period_index + 1
        body_start, body_end = trim_source_span(source, boundary, end)
        left = source[start:boundary]
        body_count = visible_character_count(source[body_start:body_end])
        literal_numbered = bool(detect_numbering_prefix_func(left))
        visual_transition = has_format_transition(features, start, boundary, end)
        source_numbering = str(
            getattr(features, "segment_numbering_features", "")
            or getattr(features, "numbering_prefix", "")
            or ""
        )
        native_list_heading = (
            source_numbering.startswith("@lvl_") and visual_transition
        )
        annual_review_heading = (
            document_mode is DocumentMode.REPORT
            and _is_annual_review_inline_heading(text, period_index, body_count)
        )
        numbered = literal_numbered or native_list_heading
        if literal_numbered:
            boundary_evidence = "NUMBERED_HEADING_TERMINATOR"
        elif native_list_heading:
            boundary_evidence = "SOURCE_LIST_HEADING_TERMINATOR"
        else:
            boundary_evidence = "VISUAL_TITLE_TERMINATOR"
        if body_count >= 5 and (numbered or visual_transition or annual_review_heading):
            candidates.append(SegmentBoundaryCandidate(
                raw_start=start,
                raw_end=boundary,
                left_type_hint="heading" if numbered or annual_review_heading else "title_or_heading",
                right_type_hint="body",
                confidence=0.99 if numbered else 0.84,
                evidence=(
                    "ANNUAL_REVIEW_HEADING_TERMINATOR" if annual_review_heading else boundary_evidence,
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
    document_mode: DocumentMode = DocumentMode.UNKNOWN,
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
        document_mode=document_mode,
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
                document_mode=document_mode,
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
    find_sign_date_suffix_span_func: Optional[
        Callable[[str], Optional[Tuple[int, int]]]
    ] = None,
) -> list[Tuple[int, int]]:
    """在“编号标题 + 一段正文”之后释放可靠的独立尾部结构。

    传入数据是源文本、已拆出的标题正文范围、下一物理段文本和结构回调。
    返回值是新的 source span 列表；正文自身仍保持为一个完整段。
    """
    if len(heading_body_spans) < 2:
        return heading_body_spans
    heading_span, body_span = heading_body_spans[:2]
    if heading_span[1] != body_span[0]:
        result: list[Tuple[int, int]] = []
        for start, end in heading_body_spans:
            value = source[start:end]
            date_suffix = (
                find_sign_date_suffix_span_func(value)
                if find_sign_date_suffix_span_func is not None
                else None
            )
            if date_suffix is None:
                result.append((start, end))
                continue
            date_start, date_end = date_suffix
            org_start, org_end = trim_source_span(source, start, start + date_start)
            if org_start < org_end and is_tail_signature_org_func(source[org_start:org_end]):
                result.extend(((org_start, org_end), (start + date_start, start + date_end)))
            else:
                result.append((start, end))
        return result

    body_start, body_end = body_span
    line_spans = source_line_spans(source)
    next_visible_line = next(
        (part.strip() for part in (next_text or "").splitlines() if part.strip()),
        "",
    )
    structural_spans: list[Tuple[int, int]] = []
    for index, (start, end) in enumerate(line_spans):
        if start <= body_start:
            continue
        value = source[start:end]
        date_suffix = (
            find_sign_date_suffix_span_func(value)
            if find_sign_date_suffix_span_func is not None
            else None
        )
        if date_suffix is not None:
            date_start, date_end = date_suffix
            org_start, org_end = trim_source_span(source, start, start + date_start)
            if org_start < org_end and is_tail_signature_org_func(source[org_start:org_end]):
                structural_spans.extend(
                    ((org_start, org_end), (start + date_start, start + date_end))
                )
                continue
        if is_strong_soft_line_structure_func(value):
            structural_spans.append((start, end))
            continue
        if (
            index + 1 < len(line_spans)
            and is_sign_date_func(source[line_spans[index + 1][0]:line_spans[index + 1][1]])
            and is_tail_signature_org_func(value)
        ):
            structural_spans.append((start, end))
            continue
        if (
            index == len(line_spans) - 1
            and is_sign_date_func(next_visible_line)
            and is_tail_signature_org_func(value)
        ):
            structural_spans.append((start, end))
    if not structural_spans:
        return heading_body_spans

    result = [heading_span]
    cursor = body_start
    for start, end in structural_spans:
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
    """兼容旧入口，校验 source span 的可见文字与范围守恒。"""
    return conservation_module.validate_source_span_partition(source, spans)


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
    document_mode: DocumentMode = DocumentMode.UNKNOWN,
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
        document_mode=document_mode,
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
