"""Paragraph physical feature extraction for DOCX importing."""

from __future__ import annotations

import re

from docxtool.document.effective_format import resolve_effective_run_format
from docxtool.document.importing.images import contains_visible_image
from docxtool.document.importing.numbering import heading_style_prefix, word_list_level_prefix
from docxtool.document.models import ParagraphFeatures, SourceRun
from docxtool.document.segmentation.source_locator import (
    apply_segment_format_features,
    utf16_length_of,
)
from docxtool.document.source_tape import SourceTape
from docxtool.document.style_config import logger


def extract_paragraph_features(paragraph, index: int, *, detect_numbering_prefix_func) -> ParagraphFeatures:
    """从 python-docx 段落读取物理格式特征。

    传入数据是 `python-docx` 的 Paragraph、物理段落序号和编号前缀检测函数。
    返回值是 `ParagraphFeatures`，包含源文本 locator、run 字体字号、加粗比例、
    对齐、缩进、图片和 Word 自动编号事实；本函数只读取物理事实，不判断最终类型。
    """
    text = paragraph.text.strip()
    source_tape = SourceTape.from_text(paragraph.text)
    features = ParagraphFeatures(
        text=text,
        paragraph_index=index,
        source_physical_paragraph_index=index,
        source_physical_text=paragraph.text,
        source_start_utf16=0,
        source_end_utf16=utf16_length_of(paragraph.text),
        source_canonical_text=source_tape.canonical_text,
        source_canonical_start_utf16=0,
        source_canonical_end_utf16=utf16_length_of(source_tape.canonical_text),
        source_fragment_text=paragraph.text,
        source_canonical_fragment_text=source_tape.canonical_text,
        source_locator_status="confirmed" if paragraph.text else "unresolved",
        source_locator_evidence=("PHYSICAL_PARAGRAPH_EXTRACTED",) if paragraph.text else (),
        source_locator_warnings=() if paragraph.text else ("SOURCE_RANGE_UNRESOLVED",),
    )

    if paragraph.style:
        features.style_name = paragraph.style.name or ""

    source_runs: list[SourceRun] = []
    source_cursor = 0
    first_run_seen = False
    if paragraph.runs:
        for run in paragraph.runs:
            run_text = run.text or ""
            run_start = source_cursor
            run_end = run_start + len(run_text)
            source_cursor = run_end
            char_count = len(re.sub(r"\s+", "", run.text or ""))
            if not char_count:
                continue
            try:
                effective = resolve_effective_run_format(run, paragraph)
                run_font = effective.east_asia_font_name or effective.ascii_font_name or ""
                run_size = effective.font_size_pt
                source_matches_run = (
                    run_end <= len(paragraph.text)
                    and paragraph.text[run_start:run_end] == run_text
                )
                if source_matches_run:
                    source_runs.append(SourceRun(
                        start=run_start,
                        end=run_end,
                        font_name=run_font,
                        east_asia_font_name=effective.east_asia_font_name,
                        ascii_font_name=effective.ascii_font_name,
                        font_size_pt=float(run_size) if run_size is not None else None,
                        bold=effective.bold,
                        italic=effective.italic,
                        underline=effective.underline,
                        explicit=effective.explicit,
                        inherited=effective.inherited,
                        known=effective.known,
                        format_sources=effective.sources,
                        format_warnings=effective.warnings,
                    ))
                if not first_run_seen:
                    features.first_run_font_name = run_font
                    features.first_run_font_size_pt = run_size
                    features.first_run_bold = effective.bold is True
                    first_run_seen = True
            except (AttributeError, TypeError, ValueError):
                continue
    features.source_run_spans = tuple(source_runs)
    apply_segment_format_features(features, features, 0, len(features.source_physical_text))

    try:
        if paragraph.alignment is not None:
            features.alignment = str(paragraph.alignment).split(".")[-1].lower()
    except Exception:
        pass

    try:
        indent = paragraph.paragraph_format.first_line_indent
        if indent is not None:
            features.first_line_indent = indent / 360000
    except Exception:
        pass

    features.numbering_prefix = detect_numbering_prefix_func(text)
    features.contains_image = contains_visible_image(paragraph._element)

    try:
        word_prefix = word_list_level_prefix(paragraph._element, text)
        if word_prefix and not features.numbering_prefix:
            features.numbering_prefix = word_prefix
            lvl = int(word_prefix[5:])
            logger.debug("[多级列表] ilvl=%s → heading%s chars=%s", lvl, lvl + 2, len(text))
    except Exception as exc:
        logger.debug("[多级列表] 提取失败: %s", exc)

    try:
        style_prefix = heading_style_prefix(features.style_name)
        if style_prefix:
            features.numbering_prefix = style_prefix
    except Exception:
        pass

    return features
