from __future__ import annotations

from docxtool.document.importer import _colon_bold_match, _contains_colon
from docxtool.document.recognition.colon import analyze_colon_structure, colon_bold_match, contains_colon


def test_contains_colon_helper_keeps_importer_facade_compatible() -> None:
    """验证冒号存在判断收口到 recognition helper 后旧入口仍一致。"""
    assert contains_colon("责任单位：办公室")
    assert contains_colon("责任单位:办公室")
    assert _contains_colon("责任单位：办公室")
    assert not contains_colon("责任单位办公室")


def test_colon_bold_match_keeps_body_label_fact_in_recognition_layer() -> None:
    """验证冒号标签加粗事实由 recognition helper 输出，旧 importer 入口保持兼容。"""
    assert colon_bold_match("原因：具体说明") == 2
    assert _colon_bold_match("原因：具体说明") == 2
    assert colon_bold_match("某某学院：具体说明") == -1
    assert colon_bold_match("原因：") == -1


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


def test_colon_analyzer_ignores_numeric_time_and_ratio_colons() -> None:
    time_line = analyze_colon_structure("（2026年8月27日11:00，某地区委员会会议中心）")
    ratio = analyze_colon_structure("本次抽查比例为1:2")
    labeled_time = analyze_colon_structure("时间：11:00")

    assert time_line.has_colon is False
    assert time_line.explanatory_body_candidate is False
    assert ratio.has_colon is False
    assert ratio.explanatory_body_candidate is False
    assert labeled_time.label == "时间"
    assert labeled_time.value == "11:00"
    assert labeled_time.key_value_candidate is True
