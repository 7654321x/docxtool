from __future__ import annotations

from docxtool.document.importer import _contains_colon
from docxtool.document.recognition.colon import analyze_colon_structure, contains_colon


def test_contains_colon_helper_keeps_importer_facade_compatible() -> None:
    """验证冒号存在判断收口到 recognition helper 后旧入口仍一致。"""
    assert contains_colon("责任单位：办公室")
    assert contains_colon("责任单位:办公室")
    assert _contains_colon("责任单位：办公室")
    assert not contains_colon("责任单位办公室")


def test_colon_analyzer_distinguishes_salutation_from_body_label() -> None:
    salutation = analyze_colon_structure("各位代表、同志们：现在开始说明会议安排。")
    organization = analyze_colon_structure("某某研究院：现将有关情况说明如下。")

    assert salutation.inline_addressing_body is True
    assert salutation.kind == "inline_addressing_body"
    assert organization.inline_addressing_body is False
    assert organization.explanatory_body_candidate is True


def test_colon_analyzer_keeps_structural_labels_separate_from_explanatory_prose() -> None:
    key_value = analyze_colon_structure("责任单位：综合管理部门")
    explanatory = analyze_colon_structure("主要原因如下：第一阶段已经完成。")

    assert key_value.key_value_candidate is True
    assert key_value.structural_label is True
    assert explanatory.key_value_candidate is False
    assert explanatory.explanatory_body_candidate is True


def test_colon_analyzer_strips_wrapping_quotes_for_structural_labels() -> None:
    quoted = analyze_colon_structure("“责任单位：综合管理部门”")

    assert quoted.label == "责任单位"
    assert quoted.value == "综合管理部门"
    assert quoted.key_value_candidate is True


def test_colon_analyzer_uses_shape_not_specific_organization_names() -> None:
    first = analyze_colon_structure("某某学院：")
    second = analyze_colon_structure("测试研究院：")

    assert first.recipient_candidate is True
    assert second.recipient_candidate is True
    assert first.organization_label is True
    assert second.organization_label is True
