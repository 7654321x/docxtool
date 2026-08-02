from __future__ import annotations

from docxtool.document.recognition.signature import (
    blocks_independent_sign_date,
    has_signature_org_shape,
    is_body_tail_context,
    is_signature_org_candidate,
    starts_with_signature_negative,
)


def test_signature_org_shape_uses_generic_suffix_not_specific_name() -> None:
    """落款单位形态判断应依赖通用组织后缀，不维护具体单位名单。"""
    assert has_signature_org_shape("星河治理委员会")
    assert has_signature_org_shape("某区工作办公室")
    assert has_signature_org_shape("园区人才保障工作组")


def test_signature_org_shape_rejects_body_or_key_value_text() -> None:
    """正文句、键值行和否定开头短句不能作为落款单位形态事实。"""
    assert starts_with_signature_negative("以上情况请审阅")
    assert not has_signature_org_shape("以上情况请审阅")
    assert not has_signature_org_shape("责任单位：办公室")
    assert not has_signature_org_shape("这里是正文内容。")


def test_signature_org_shape_respects_length_boundary() -> None:
    """调用方可传入长度上限，返回对应落款候选形态判断结果。"""
    text = "测试市人民政府办公室"
    assert has_signature_org_shape(text, max_length=20)
    assert not has_signature_org_shape(text, max_length=4)


def test_signature_body_tail_context_uses_final_structural_type() -> None:
    """尾部落款上下文只依赖最终结构类型，返回是否可继续识别尾部结构。"""
    assert is_body_tail_context("body")
    assert is_body_tail_context("attachment_note_item")
    assert not is_body_tail_context("title")
    assert not is_body_tail_context(None)


def test_blocks_independent_sign_date_keeps_key_value_exception() -> None:
    """独立日期阻断判断接收上一结构文本，返回是否阻止日期单独成尾部日期。"""
    assert not blocks_independent_sign_date("")
    assert not blocks_independent_sign_date("责任单位：办公室")
    assert blocks_independent_sign_date("以上情况请审阅")
    assert blocks_independent_sign_date("联系人：张三")


def test_signature_org_candidate_requires_body_context_and_next_date() -> None:
    """落款候选判断接收当前行和上下文事实，返回是否具备落款单位候选资格。"""
    assert is_signature_org_candidate(
        "测试市人民政府办公室",
        "2025年10月15日",
        last_structural_type="body",
        is_attachment_note=False,
        current_is_sign_date=False,
        next_is_sign_date=True,
    )
    assert not is_signature_org_candidate(
        "测试市人民政府办公室",
        "下一段正文",
        last_structural_type="body",
        is_attachment_note=False,
        current_is_sign_date=False,
        next_is_sign_date=False,
    )
    assert not is_signature_org_candidate(
        "测试市人民政府办公室",
        "2025年10月15日",
        last_structural_type="title",
        is_attachment_note=False,
        current_is_sign_date=False,
        next_is_sign_date=True,
    )
