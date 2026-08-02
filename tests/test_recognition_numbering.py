from __future__ import annotations

from docxtool.document.models import ParagraphFeatures
from docxtool.document.recognition.numbering import (
    find_numbered_bold_pos,
    looks_like_damaged_heading,
    match_numbering,
    match_style_or_level,
)


def _normalize_text(text: str) -> str:
    """测试用最小清理函数，传入文本并返回去首尾空白后的文本。"""
    return (text or "").strip()


def _contains_colon(text: str) -> bool:
    """测试用冒号判断函数，传入文本并返回是否含中英文冒号。"""
    return "：" in text or ":" in text


def test_match_numbering_keeps_existing_heading_prefix_mapping() -> None:
    """字面标题编号应映射为旧 type_id 和原始前缀。"""
    assert match_numbering("一、一级标题", normalize_text=_normalize_text) == ("heading1", "一、")
    assert match_numbering("二.损坏一级标题", normalize_text=_normalize_text) == ("heading1", "二.")
    assert match_numbering("（一）二级标题", normalize_text=_normalize_text) == ("heading2", "（一）")
    assert match_numbering("1.三级标题", normalize_text=_normalize_text) == ("heading3", "1.")
    assert match_numbering("（1）四级标题", normalize_text=_normalize_text) == ("heading4", "（1）")


def test_match_numbering_filters_heading4_when_colon_is_present() -> None:
    """四级编号行含冒号时不作为标题编号候选，交给冒号结构继续判断。"""
    assert match_numbering(
        "（1）责任单位：办公室",
        normalize_text=_normalize_text,
        contains_colon=_contains_colon,
    ) == (None, None)


def test_match_style_or_level_maps_word_numbering_without_overriding_body_leads() -> None:
    """Word 样式/列表事实只生成标题候选，不覆盖“一是/一要”正文引导句。"""
    assert match_style_or_level("自动列表标题", ParagraphFeatures(numbering_prefix="@lvl_0")) == ("heading2", "")
    assert match_style_or_level("自动列表标题", ParagraphFeatures(numbering_prefix="@lvl_2")) == ("heading4", "")
    assert match_style_or_level("样式标题", ParagraphFeatures(numbering_prefix="@style_heading1")) == ("heading1", "")
    assert match_style_or_level(
        "一是普通正文",
        ParagraphFeatures(numbering_prefix="@lvl_0"),
        normalize_text=_normalize_text,
    ) == (None, None)


def test_find_numbered_bold_pos_and_damaged_heading_are_structure_facts() -> None:
    """强调句位置和损坏标题判断只返回事实，不直接写入最终类型。"""
    assert find_numbered_bold_pos("一是加强学习。后接正文", normalize_text=_normalize_text) == 0
    assert find_numbered_bold_pos("比如：具体说明", normalize_text=_normalize_text) == 0
    assert find_numbered_bold_pos("普通正文", normalize_text=_normalize_text) == -1
    assert looks_like_damaged_heading("一，加强领导")
    assert not looks_like_damaged_heading("一是加强领导。后接正文")
