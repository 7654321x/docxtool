from __future__ import annotations

from docxtool.document.recognition.state import (
    LEGACY_FLOW,
    legacy_flow_allows,
    legacy_repair_heading4_colon,
    legacy_repair_heading_level,
)


def test_legacy_flow_allows_document_opening_candidates() -> None:
    """旧 Flow 判断接收候选和空上一类型，返回文档开头允许的结构。"""
    assert legacy_flow_allows("title", None)
    assert legacy_flow_allows("body", "")
    assert not legacy_flow_allows("sign_date", None)


def test_legacy_flow_keeps_heading1_report_alias() -> None:
    """旧 Flow 判断接收报告标题候选，返回与 heading1 相同的兼容放行结果。"""
    assert legacy_flow_allows("heading1_report", "title")
    assert legacy_flow_allows("heading1_report", "body")
    assert not legacy_flow_allows("heading1_report", "sign_org")


def test_legacy_flow_rejects_disallowed_known_transition() -> None:
    """旧 Flow 判断接收已知上一类型，返回是否拒绝不合法的下一类型。"""
    assert legacy_flow_allows("sign_date", "sign_org")
    assert not legacy_flow_allows("attachment_title", "sign_org")
    assert not legacy_flow_allows("sign_date", "body")


def test_legacy_flow_preserves_unknown_previous_type_fallback() -> None:
    """旧 Flow 判断接收未知上一类型时，返回兼容旧 importer 的默认放行结果。"""
    assert "body" in LEGACY_FLOW
    assert legacy_flow_allows("body", "unknown_legacy_type")


def test_legacy_repair_heading_level_caps_skipped_levels() -> None:
    """标题层级修复接收候选类型和当前层级，返回跳级修正后的类型。"""
    assert legacy_repair_heading_level("heading4", 1) == "heading2"
    assert legacy_repair_heading_level("heading3", 2) == "heading3"
    assert legacy_repair_heading_level("body", 1) == "body"


def test_legacy_repair_heading_level_keeps_report_heading() -> None:
    """标题层级修复接收报告标题类型，返回不参与普通跳级修复的原类型。"""
    assert legacy_repair_heading_level("heading1_report", 0) == "heading1_report"


def test_legacy_repair_heading4_colon_demotes_only_colon_heading4() -> None:
    """四级标题冒号修复接收类型和冒号事实，返回正文或原类型。"""
    assert legacy_repair_heading4_colon("heading4", contains_colon=True) == "body"
    assert legacy_repair_heading4_colon("heading4", contains_colon=False) == "heading4"
    assert legacy_repair_heading4_colon("heading3", contains_colon=True) == "heading3"
