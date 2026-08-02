from __future__ import annotations

from docxtool.document.recognition.signature import (
    has_signature_org_shape,
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
