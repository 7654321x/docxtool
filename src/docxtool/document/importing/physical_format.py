"""DOCX run 和段落格式的物理事实读取。"""

from __future__ import annotations

import re
from typing import Any

from docxtool.document.effective_format import resolve_effective_run_format
from docxtool.document.models import SourceRun
from docxtool.document.segmentation.source_locator import apply_segment_format_features


def apply_physical_format_features(paragraph, features: Any) -> None:
    """把现有 run 与段落格式事实写入 ``ParagraphFeatures``。

    传入 python-docx 段落和已初始化的特征对象，无返回值。该函数只移动
    原导入代码的位置；run 游标、空白 run 跳过、异常吞吐、单位换算和初始
    segment 格式聚合顺序均保持不变。
    """
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
