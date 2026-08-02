from __future__ import annotations

from docxtool.document.recognition.attachment import (
    can_start_attachment_note,
    is_attachment_boundary_text,
    is_attachment_item_text,
    is_attachment_note_text,
    match_attachment_note,
)


def test_attachment_note_and_item_shapes_are_plain_facts() -> None:
    """附件说明和附件项 helper 只返回文本形态事实，不决定最终类型。"""
    match = match_attachment_note("附件：1. 基本情况")

    assert match is not None
    assert match.group(1) == "1. 基本情况"
    assert is_attachment_note_text("附件：测试材料")
    assert is_attachment_item_text("2. 具体情况")
    assert is_attachment_item_text("3、补充材料")
    assert not is_attachment_note_text("正文中提到附件：材料")
    assert not is_attachment_item_text("一、一级标题")


def test_attachment_boundary_can_include_page_mark_callback() -> None:
    """附件边界 helper 可接收附件页标识判断器，返回合并后的边界事实。"""
    assert is_attachment_boundary_text("附件：1. 基本情况")
    assert is_attachment_boundary_text("附件1", is_attachment_page_mark=lambda text: text == "附件1")
    assert not is_attachment_boundary_text("附件1")
    assert not is_attachment_boundary_text("普通正文")


def test_can_start_attachment_note_uses_state_without_assigning_type() -> None:
    """附件说明起点许可只消费结构状态，返回布尔值，不写最终段落类型。"""
    assert can_start_attachment_note(
        has_seen_real_body=True,
        attachment_page_mode=False,
        signature_complete=False,
        last_structural_type="body",
    )
    assert can_start_attachment_note(
        has_seen_real_body=True,
        attachment_page_mode=False,
        signature_complete=True,
        last_structural_type="sign_date",
    )
    assert not can_start_attachment_note(
        has_seen_real_body=False,
        attachment_page_mode=False,
        signature_complete=False,
        last_structural_type="body",
    )
    assert not can_start_attachment_note(
        has_seen_real_body=True,
        attachment_page_mode=True,
        signature_complete=False,
        last_structural_type="body",
    )
    assert not can_start_attachment_note(
        has_seen_real_body=True,
        attachment_page_mode=False,
        signature_complete=True,
        last_structural_type="body",
    )
