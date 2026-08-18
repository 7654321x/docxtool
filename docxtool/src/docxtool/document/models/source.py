"""Source-coordinate models shared by importing, segmentation, and SDK code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class SourceRun:
    """记录一个源 run 的格式事实。

    传入数据是物理段落内的 code-point 起止位置、字体、字号和格式来源。
    返回值是不可变数据对象，供导入层、拆段层和宿主定位逻辑复用。
    """

    start: int
    end: int
    font_name: str
    east_asia_font_name: Optional[str]
    ascii_font_name: Optional[str]
    font_size_pt: Optional[float]
    bold: Optional[bool]
    italic: Optional[bool]
    underline: Optional[bool]
    explicit: bool
    inherited: bool
    known: bool
    format_sources: Tuple[str, ...] = ()
    format_warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SegmentBoundaryCandidate:
    """记录一个保守的逻辑段边界候选。

    传入数据是原物理段落中的原始起止位置、左右类型提示和证据。
    返回值是不可变候选对象；它只描述边界，不修改源文本。
    """

    raw_start: int
    raw_end: int
    left_type_hint: str
    right_type_hint: str
    confidence: float
    evidence: Tuple[str, ...]
    warnings: Tuple[str, ...] = ()
