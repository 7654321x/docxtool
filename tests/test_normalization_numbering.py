from __future__ import annotations

import re
from types import SimpleNamespace

from docxtool.document.normalization.numbering import (
    assign_heading_numbering,
    fix_heading_numbering_gaps,
    strip_numbering_prefix,
    style_key_to_rule_row,
)


def test_strip_numbering_prefix_uses_explicit_prefix_first() -> None:
    """编号剥离接收文本和显式前缀，返回不含编号的标题正文。"""
    assert strip_numbering_prefix("一、改革发展", "一、") == "改革发展"
    assert strip_numbering_prefix("4..压实责任", "4.") == "压实责任"


def test_strip_numbering_prefix_handles_word_auto_number_marker() -> None:
    """编号剥离接收 Word 自动编号补标文本，返回补标冒号后的正文。"""
    assert strip_numbering_prefix("@lvl_0:自动标题") == "自动标题"


def test_strip_numbering_prefix_falls_back_to_numbering_patterns() -> None:
    """编号剥离接收兜底正则列表，返回匹配首个编号形态后的正文。"""
    patterns = [
        (re.compile(r"^（[一二三]）"), "heading2"),
        (re.compile(r"^\d+[.．]"), "heading3"),
    ]
    assert strip_numbering_prefix("（一）部署安排", numbering_patterns=patterns) == "部署安排"
    assert strip_numbering_prefix("1.具体措施", numbering_patterns=patterns) == "具体措施"


def test_style_key_to_rule_row_preserves_legacy_mapping() -> None:
    """样式行号映射接收旧层级 key，返回 importer 编号分配兼容行号。"""
    assert style_key_to_rule_row("a") == 1
    assert style_key_to_rule_row("b") == 2
    assert style_key_to_rule_row("c") == 3
    assert style_key_to_rule_row("d") == 4
    assert style_key_to_rule_row("unknown") == 5


def _paragraph(type_id: str, meta: dict | None = None) -> SimpleNamespace:
    """测试辅助：传入类型和 meta，返回段落形状对象。"""
    return SimpleNamespace(type_id=type_id, meta=dict(meta or {}))


def _rules() -> list[SimpleNamespace]:
    """测试辅助：返回 importer 编号分配兼容的样式规则列表。"""
    return [
        SimpleNamespace(numbering_pattern=""),
        SimpleNamespace(numbering_pattern="{a}、"),
        SimpleNamespace(numbering_pattern="（{b}）"),
        SimpleNamespace(numbering_pattern="{c}."),
        SimpleNamespace(numbering_pattern="（{d}）"),
        SimpleNamespace(numbering_pattern=""),
    ]


def test_assign_heading_numbering_writes_legacy_meta_sequence() -> None:
    """编号分配接收已识别标题和规则，写入旧 importer 兼容编号 meta。"""
    paragraphs = [
        _paragraph("heading1"),
        _paragraph("heading2"),
        _paragraph("heading3"),
        _paragraph("heading4"),
        _paragraph("body"),
        _paragraph("heading2", {"heading2_cont": True}),
    ]

    assign_heading_numbering(paragraphs, _rules())

    assert [paragraph.meta.get("numbering", "") for paragraph in paragraphs] == [
        "一、",
        "（一）",
        "1.",
        "（1）",
        "",
        "",
    ]


def test_assign_heading_numbering_resets_after_attachment_page_mark() -> None:
    """编号分配接收附件页标记时，后续标题编号从一重新开始。"""
    paragraphs = [
        _paragraph("heading1"),
        _paragraph("attachment_page_mark"),
        _paragraph("heading1"),
    ]

    assign_heading_numbering(paragraphs, _rules())

    assert [paragraph.meta.get("numbering", "") for paragraph in paragraphs] == ["一、", "", "一、"]


def test_fix_heading_numbering_gaps_preserves_old_repair_behavior() -> None:
    """跳号修复接收已编号标题列表，原地修正一至四级编号 meta。"""
    paragraphs = [
        _paragraph("heading1", {"numbering": "二、"}),
        _paragraph("heading2", {"numbering": "（三）"}),
        _paragraph("heading3", {"numbering": "5."}),
        _paragraph("heading4", {"numbering": "（6）"}),
    ]

    fix_heading_numbering_gaps(paragraphs)

    assert [paragraph.meta["numbering"] for paragraph in paragraphs] == [
        "一、",
        "（一）",
        "1.",
        "（1）",
    ]
