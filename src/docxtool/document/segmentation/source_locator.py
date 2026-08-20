"""Source locator and segment-format helpers for logical paragraph splitting."""

from __future__ import annotations

from collections import Counter
from typing import Callable, Iterable, Optional, Tuple

from docxtool.document.effective_format import FORMAT_COVERAGE_CONFIRMED
from docxtool.document.models import ParagraphFeatures
from docxtool.document.source_tape import SourceTape, canonicalize_text, utf16_length


_STRUCTURALLY_INVISIBLE_CHARACTERS = frozenset(
    "\u200b\u200c\u200d\u2060\ufeff"
)


def is_structurally_invisible_character(value: str) -> bool:
    """返回单个字符在逻辑分段中是否不构成可见正文。"""
    return bool(
        value
        and (
            value.isspace()
            or value in _STRUCTURALLY_INVISIBLE_CHARACTERS
        )
    )


def utf16_length_of(value: str) -> int:
    """计算字符串的 UTF-16 code unit 长度。

    传入数据是 Python 字符串。返回值是宿主定位协议使用的 UTF-16 长度，
    不表示 WPS 或 Word 的实际 Range。
    """
    return utf16_length(value)


def build_physical_source_features(
    raw_text: str,
    paragraph_index: int,
) -> ParagraphFeatures:
    """构建物理段落进入导入链时的初始 source locator 特征。

    传入数据是 python-docx 段落原文和物理段落序号。返回值保留原有
    raw/canonical UTF-16 范围、片段、证据和空段 unresolved 状态；本函数
    不读取 run 格式、编号、图片或样式，也不判断段落类型。
    """
    source_tape = SourceTape.from_text(raw_text)
    return ParagraphFeatures(
        text=raw_text.strip(),
        paragraph_index=paragraph_index,
        source_physical_paragraph_index=paragraph_index,
        source_physical_text=raw_text,
        source_start_utf16=0,
        source_end_utf16=utf16_length_of(raw_text),
        source_canonical_text=source_tape.canonical_text,
        source_canonical_start_utf16=0,
        source_canonical_end_utf16=utf16_length_of(source_tape.canonical_text),
        source_fragment_text=raw_text,
        source_canonical_fragment_text=source_tape.canonical_text,
        source_locator_status="confirmed" if raw_text else "unresolved",
        source_locator_evidence=("PHYSICAL_PARAGRAPH_EXTRACTED",) if raw_text else (),
        source_locator_warnings=() if raw_text else ("SOURCE_RANGE_UNRESOLVED",),
    )


def trim_source_span(source: str, start: int, end: int) -> Tuple[int, int]:
    """修剪源文本范围两端空白并保留原坐标体系。

    传入数据是源文本和 code-point 起止位置。返回值是修剪后的起止位置，
    供拆段和 locator 映射使用。
    """
    while start < end and is_structurally_invisible_character(source[start]):
        start += 1
    while end > start and is_structurally_invisible_character(source[end - 1]):
        end -= 1
    return start, end


def source_line_spans(source: str) -> list[Tuple[int, int]]:
    """提取源物理段落中非空可见行的原始范围。

    传入数据是原始物理段落文本。返回值是按顺序排列的 `(start, end)`
    范围列表，不通过反向文本查找定位。
    """
    spans: list[Tuple[int, int]] = []
    line_start = 0
    index = 0
    while index <= len(source):
        if index == len(source) or source[index] in "\r\n":
            start, end = trim_source_span(source, line_start, index)
            if start < end:
                spans.append((start, end))
            if index < len(source) and source[index] == "\r" and index + 1 < len(source) and source[index + 1] == "\n":
                index += 1
            line_start = index + 1
        index += 1
    return spans


def visible_character_count(value: str) -> int:
    """统计去除空白后的可见字符数。

    传入数据是一段文本。返回值是用于边界阈值、格式覆盖和加粗比例计算
    的可见字符数量。
    """
    return sum(
        1
        for character in value or ""
        if not is_structurally_invisible_character(character)
    )


def set_source_locator(
    child: ParagraphFeatures,
    parent: ParagraphFeatures,
    start: int,
    end: int,
) -> None:
    """把一个逻辑段绑定到父物理段的精确源范围。

    传入数据是子段特征、父段特征和父段原文中的 code-point 起止位置。
    函数返回 `None`，直接写入子段的 raw/canonical UTF-16 locator 字段。
    """
    child.source_physical_paragraph_index = parent.source_physical_paragraph_index
    child.source_physical_text = parent.source_physical_text
    tape = SourceTape.from_text(parent.source_physical_text)
    child.source_canonical_text = tape.canonical_text
    if parent.source_physical_paragraph_index is None:
        child.source_locator_status = "unresolved"
        child.source_locator_warnings = ("SOURCE_PHYSICAL_PARAGRAPH_MISSING",)
        return
    if not 0 <= start < end <= len(tape.raw_text):
        child.source_locator_status = "unresolved"
        child.source_locator_warnings = ("SOURCE_RANGE_OUT_OF_BOUNDS",)
        return
    canonical_range = tape.canonical_range_for_raw_span(start, end)
    raw_start = tape.raw_offset_utf16(start)
    raw_end = tape.raw_offset_utf16(end)
    if canonical_range is None or raw_start is None or raw_end is None:
        child.source_locator_status = "unresolved"
        child.source_locator_warnings = ("SOURCE_RANGE_UNRESOLVED",)
        return
    raw_fragment = tape.raw_text[start:end]
    canonical_fragment = canonicalize_text(raw_fragment)
    child.source_start_utf16 = raw_start
    child.source_end_utf16 = raw_end
    child.source_canonical_start_utf16 = canonical_range[0]
    child.source_canonical_end_utf16 = canonical_range[1]
    child.source_fragment_text = raw_fragment
    child.source_canonical_fragment_text = canonical_fragment
    child.source_locator_status = "confirmed"
    child.source_locator_evidence = ("RAW_RANGE_READBACK_MATCH", "CANONICAL_RANGE_MAPPED")
    child.source_locator_warnings = ()


def apply_segment_format_features(
    child: ParagraphFeatures,
    parent: ParagraphFeatures,
    start: int,
    end: int,
) -> None:
    """根据 run 与逻辑段范围的交集计算段内格式特征。

    传入数据是子段特征、父段特征和父段原文中的 code-point 范围。
    函数返回 `None`，直接写入子段的字体、字号、加粗比例和格式覆盖字段。
    """
    source = parent.source_physical_text
    font_weights: Counter[str] = Counter()
    east_asia_weights: Counter[str] = Counter()
    ascii_weights: Counter[str] = Counter()
    size_weights: Counter[float] = Counter()
    characters = bold_characters = italic_characters = underline_characters = 0
    explicit_characters = inherited_characters = mapped_format_characters = 0
    run_count = 0
    format_sources = []
    format_warnings = []
    for run in parent.source_run_spans:
        overlap_start = max(start, run.start)
        overlap_end = min(end, run.end)
        if overlap_start >= overlap_end:
            continue
        count = visible_character_count(source[overlap_start:overlap_end])
        if not count:
            continue
        run_count += 1
        characters += count
        if run.font_name:
            font_weights[run.font_name] += count
        if run.east_asia_font_name:
            east_asia_weights[run.east_asia_font_name] += count
        if run.ascii_font_name:
            ascii_weights[run.ascii_font_name] += count
        if run.font_size_pt is not None:
            size_weights[float(run.font_size_pt)] += count
        if run.bold is True:
            bold_characters += count
        if run.italic is True:
            italic_characters += count
        if run.underline is True:
            underline_characters += count
        if run.explicit:
            explicit_characters += count
        if run.inherited:
            inherited_characters += count
        if run.known:
            mapped_format_characters += count
        format_sources.extend(run.format_sources)
        format_warnings.extend(run.format_warnings)

    child.segment_style_name = parent.style_name
    child.segment_alignment = parent.alignment
    child.segment_numbering_features = child.numbering_prefix or parent.numbering_prefix
    child.segment_run_count = run_count
    child.segment_visible_char_count = characters
    child.segment_mapped_format_char_count = mapped_format_characters
    child.segment_format_coverage_ratio = (
        mapped_format_characters / characters if characters else 0.0
    )
    child.segment_format_sources = tuple(dict.fromkeys(format_sources))
    if start == 0 and end == len(source):
        child.segment_position_in_physical_paragraph = "whole"
    elif start == 0:
        child.segment_position_in_physical_paragraph = "start"
    elif end == len(source):
        child.segment_position_in_physical_paragraph = "end"
    else:
        child.segment_position_in_physical_paragraph = "middle"

    if not characters:
        child.segment_font_name = parent.font_name
        child.segment_dominant_font_name = parent.dominant_font_name or parent.font_name
        child.segment_font_size_pt = parent.font_size_pt
        child.segment_weighted_font_size_pt = parent.weighted_font_size or parent.font_size_pt
        child.segment_bold_char_ratio = parent.bold_char_ratio
        child.segment_italic_char_ratio = parent.italic_char_ratio
        child.segment_explicit_format_ratio = parent.explicitly_formatted_char_ratio
        child.segment_inherited_format_ratio = 0.0
        child.segment_format_status = "unknown"
        child.segment_format_warnings = tuple(dict.fromkeys(
            list(format_warnings) + ["NO_VISIBLE_RUN_FORMAT_COVERAGE"]
        ))
        return

    dominant_font = font_weights.most_common(1)[0][0] if font_weights else parent.font_name
    weighted_size = (
        sum(size * weight for size, weight in size_weights.items()) / sum(size_weights.values())
        if size_weights else parent.font_size_pt
    )
    child.segment_font_name = dominant_font
    child.segment_dominant_font_name = dominant_font
    child.segment_font_name_east_asia = (
        east_asia_weights.most_common(1)[0][0] if east_asia_weights else ""
    )
    child.segment_font_name_ascii = (
        ascii_weights.most_common(1)[0][0] if ascii_weights else ""
    )
    child.segment_font_size_pt = weighted_size
    child.segment_weighted_font_size_pt = weighted_size
    child.segment_bold_char_ratio = bold_characters / characters
    child.segment_italic_char_ratio = italic_characters / characters
    child.segment_underline_char_ratio = underline_characters / characters
    child.segment_explicit_format_ratio = explicit_characters / characters
    child.segment_inherited_format_ratio = inherited_characters / characters
    child.segment_has_mixed_fonts = len(font_weights) > 1 or len(east_asia_weights) > 1 or len(ascii_weights) > 1
    child.segment_has_mixed_sizes = len(size_weights) > 1
    if child.segment_format_coverage_ratio >= FORMAT_COVERAGE_CONFIRMED:
        child.segment_format_status = "confirmed"
    elif child.segment_format_coverage_ratio > 0:
        child.segment_format_status = "review"
        format_warnings.append("PARTIAL_RUN_FORMAT_COVERAGE")
    else:
        child.segment_format_status = "unknown"
        format_warnings.append("NO_RUN_FORMAT_COVERAGE")
    child.segment_format_warnings = tuple(dict.fromkeys(format_warnings))

    child.font_name = dominant_font
    child.dominant_font_name = dominant_font
    child.font_size_pt = weighted_size
    child.weighted_font_size = weighted_size
    child.max_font_size = max(size_weights) if size_weights else weighted_size
    child.min_font_size = min(size_weights) if size_weights else weighted_size
    child.bold_char_ratio = child.segment_bold_char_ratio
    child.italic_char_ratio = child.segment_italic_char_ratio
    child.explicitly_formatted_char_ratio = child.segment_explicit_format_ratio
    child.bold = child.segment_bold_char_ratio >= 0.5


def build_segment_features(
    parent: ParagraphFeatures,
    start: int,
    end: int,
    *,
    paragraph_index: int,
    is_new_line: bool = False,
    inline_lead_bold_func: Optional[Callable[[str, int, int, ParagraphFeatures], bool]] = None,
) -> ParagraphFeatures:
    """从父物理段特征构建一个逻辑段特征对象。

    传入数据是父段特征、源文本范围、逻辑段序号、是否来自软换行和可选
    行内加粗判断回调。返回值是已写入 locator、段内格式和强调标记的
    `ParagraphFeatures`，不决定最终段落类型。
    """
    child = ParagraphFeatures(
        font_name=parent.font_name,
        font_size_pt=parent.font_size_pt,
        bold=parent.bold,
        alignment=parent.alignment,
        style_name=parent.style_name,
        numbering_prefix=parent.numbering_prefix,
        native_numbering=(
            parent.native_numbering
            if not parent.source_physical_text[:start].strip()
            else None
        ),
        paragraph_index=paragraph_index,
        is_new_line=is_new_line,
        dominant_font_name=parent.dominant_font_name,
        weighted_font_size=parent.weighted_font_size,
        max_font_size=parent.max_font_size,
        min_font_size=parent.min_font_size,
        bold_char_ratio=parent.bold_char_ratio,
        italic_char_ratio=parent.italic_char_ratio,
        explicitly_formatted_char_ratio=parent.explicitly_formatted_char_ratio,
        page_break_before=parent.page_break_before,
        layout_preservation_hint=parent.layout_preservation_hint,
        layout_preservation_evidence=parent.layout_preservation_evidence,
    )
    set_source_locator(child, parent, start, end)
    apply_segment_format_features(child, parent, start, end)
    if inline_lead_bold_func is not None:
        child.inline_lead_bold = inline_lead_bold_func(
            parent.source_physical_text, start, end, parent
        )
    return child


def build_unresolved_empty_segment_features(
    parent: ParagraphFeatures,
    *,
    paragraph_index: int,
) -> ParagraphFeatures:
    """构建空可见文本逻辑段的未解析定位特征。

    传入数据是父物理段特征和逻辑段序号。返回值是保留物理段来源、
    标记 `SOURCE_RANGE_UNRESOLVED` 的 `ParagraphFeatures`，用于分节或
    分页符空段占位，不决定最终段落类型。
    """
    child = ParagraphFeatures(
        font_name=parent.font_name,
        font_size_pt=parent.font_size_pt,
        bold=parent.bold,
        alignment=parent.alignment,
        style_name=parent.style_name,
        numbering_prefix=parent.numbering_prefix,
        native_numbering=parent.native_numbering,
        paragraph_index=paragraph_index,
        page_break_before=parent.page_break_before,
        layout_preservation_hint=parent.layout_preservation_hint,
        layout_preservation_evidence=parent.layout_preservation_evidence,
    )
    child.source_physical_paragraph_index = parent.source_physical_paragraph_index
    child.source_physical_text = parent.source_physical_text
    child.source_canonical_text = canonicalize_text(parent.source_physical_text)
    child.source_locator_warnings = ("SOURCE_RANGE_UNRESOLVED",)
    return child


def assign_segment_ordinals(features: Iterable[ParagraphFeatures]) -> None:
    """为同一物理段拆出的逻辑段写入顺序号和总数。

    传入数据是一组 `ParagraphFeatures`，函数返回 `None` 并原地写入
    `segment_index` 与 `segment_count`。没有物理段索引的特征会被跳过。
    """
    physical_segments: dict[int, list[ParagraphFeatures]] = {}
    for feature in features:
        physical_index = feature.source_physical_paragraph_index
        if physical_index is not None:
            physical_segments.setdefault(physical_index, []).append(feature)
    for features_for_physical in physical_segments.values():
        total = len(features_for_physical)
        for segment_index, feature in enumerate(features_for_physical):
            feature.segment_index = segment_index
            feature.segment_count = total


def inherit_source_locator(
    child: ParagraphFeatures,
    parent: ParagraphFeatures,
    fragment: str,
    search_from: int = 0,
) -> int:
    """兼容旧调用方的文本查找式 source locator 回退。

    传入数据是子段特征、父段特征、待查找文本和搜索起点。返回值是下一次
    搜索的起点；由于重复文本无法证明唯一绑定，状态只标记为 review。
    """
    child.source_physical_paragraph_index = parent.source_physical_paragraph_index
    child.source_physical_text = parent.source_physical_text
    child.source_canonical_text = canonicalize_text(child.source_physical_text)
    if parent.source_physical_paragraph_index is None:
        child.source_locator_status = "unresolved"
        child.source_locator_warnings = ("SOURCE_PHYSICAL_PARAGRAPH_MISSING",)
        return search_from
    source = parent.source_physical_text or ""
    value = fragment or ""
    start = source.find(value, max(0, search_from))
    if start < 0 and value.strip() != value:
        value = value.strip()
        start = source.find(value, max(0, search_from))
    if start < 0:
        child.source_start_utf16 = None
        child.source_end_utf16 = None
        child.source_locator_status = "unresolved"
        child.source_locator_warnings = ("SOURCE_RANGE_UNRESOLVED",)
        return search_from
    end = start + len(value)
    child.source_start_utf16 = utf16_length_of(source[:start])
    child.source_end_utf16 = utf16_length_of(source[:end])
    tape = SourceTape.from_text(source)
    canonical_range = tape.canonical_range_for_raw_span(start, end)
    child.source_canonical_start_utf16 = canonical_range[0] if canonical_range else None
    child.source_canonical_end_utf16 = canonical_range[1] if canonical_range else None
    child.source_fragment_text = source[start:end]
    child.source_canonical_fragment_text = canonicalize_text(child.source_fragment_text)
    child.source_locator_status = "review"
    child.source_locator_evidence = ("LEGACY_TEXT_SEARCH",)
    child.source_locator_warnings = ("SOURCE_OCCURRENCE_AMBIGUOUS",)
    return end
