"""Paragraph-level document models used by the import pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from docxtool.document.models.source import SourceRun


@dataclass(frozen=True)
class NativeNumbering:
    """记录一个段落解析后的 Word/WPS 原生编号事实。"""

    num_id: int
    abstract_num_id: int
    ilvl: int
    num_fmt: str
    lvl_text: str
    start: int
    start_override: Optional[int]
    ordinal: int
    family_id: str
    num_xml: object
    abstract_num_xml: object
    num_pr_xml: object

    @property
    def effective_start(self) -> int:
        """返回当前编号实例实际使用的起始序号。"""
        return self.start_override if self.start_override is not None else self.start


@dataclass
class ParagraphFeatures:
    """记录一个逻辑段落可观测到的物理特征。

    传入数据来自 DOCX 段落、run、样式、编号和 source locator。返回值是可变
    特征对象，供拆段、旧分类器、识别候选和 SDK 定位共同读取。
    """

    text: str = ""
    style_name: str = ""
    font_name: str = ""
    font_size_pt: Optional[float] = None
    bold: bool = False
    alignment: str = ""
    first_line_indent: float = 0.0
    numbering_prefix: str = ""
    native_numbering: Optional[NativeNumbering] = None
    paragraph_index: int = 0
    source_physical_paragraph_index: Optional[int] = None
    source_physical_text: str = ""
    source_start_utf16: Optional[int] = None
    source_end_utf16: Optional[int] = None
    source_canonical_text: str = ""
    source_canonical_start_utf16: Optional[int] = None
    source_canonical_end_utf16: Optional[int] = None
    source_fragment_text: str = ""
    source_canonical_fragment_text: str = ""
    source_locator_status: str = "unresolved"
    source_locator_evidence: Tuple[str, ...] = ()
    source_locator_warnings: Tuple[str, ...] = ()
    source_run_spans: Tuple[SourceRun, ...] = ()
    segment_font_name: str = ""
    segment_dominant_font_name: str = ""
    segment_font_name_east_asia: str = ""
    segment_font_name_ascii: str = ""
    segment_font_size_pt: Optional[float] = None
    segment_weighted_font_size_pt: Optional[float] = None
    segment_bold_char_ratio: float = 0.0
    segment_italic_char_ratio: float = 0.0
    segment_underline_char_ratio: float = 0.0
    segment_explicit_format_ratio: float = 0.0
    segment_inherited_format_ratio: float = 0.0
    segment_run_count: int = 0
    segment_visible_char_count: int = 0
    segment_mapped_format_char_count: int = 0
    segment_format_coverage_ratio: float = 0.0
    segment_format_status: str = "unknown"
    segment_format_warnings: Tuple[str, ...] = ()
    segment_format_sources: Tuple[str, ...] = ()
    segment_style_name: str = ""
    segment_has_mixed_fonts: bool = False
    segment_has_mixed_sizes: bool = False
    segment_numbering_features: str = ""
    segment_alignment: str = ""
    segment_position_in_physical_paragraph: str = "whole"
    segment_index: int = 0
    segment_count: int = 1
    is_in_table: bool = False
    contains_image: bool = False
    page_break_before: bool = False
    is_new_line: bool = False
    first_run_font_name: str = ""
    first_run_font_size_pt: Optional[float] = None
    first_run_bold: bool = False
    dominant_font_name: str = ""
    weighted_font_size: Optional[float] = None
    max_font_size: Optional[float] = None
    min_font_size: Optional[float] = None
    bold_char_ratio: float = 0.0
    italic_char_ratio: float = 0.0
    explicitly_formatted_char_ratio: float = 0.0
    inline_lead_bold: bool = False
    layout_preservation_hint: bool = False
    layout_preservation_evidence: Tuple[str, ...] = ()


@dataclass
class InlineToken:
    """记录逻辑段落内必须保留的行内 token。

    传入数据是 token 类型和可选文本。返回值是可变对象，供导入层保存制表符、
    软换行、分页符和文本片段，渲染时按顺序重建。
    """

    kind: str
    text: str = ""


@dataclass
class ParagraphData:
    """记录导入后的一个逻辑段落。

    传入数据是段落文本、最终类型、原始文本、物理特征、元数据和行内 token。
    返回值是可变段落模型，贯穿 importer、recognition、normalizer 和 renderer。
    """

    text: str
    type_id: str
    original_text: str
    features: ParagraphFeatures
    meta: dict = field(default_factory=dict)
    inline_tokens: List[InlineToken] = field(default_factory=list)
