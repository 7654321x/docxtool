from __future__ import annotations

from docxtool.document.recognition.document_mode import (
    detect_legacy_doc_type,
    has_doc_type_keyword,
    has_title_keyword,
    legacy_glossary_item_score,
    legacy_glossary_title_score,
    legacy_heading_addressing_score,
    legacy_report_addressing_score,
    legacy_report_heading_score,
    legacy_title2_score,
    starts_report_heading,
    starts_report_heading_or_addressing,
)
from docxtool.document.recognition.features import (
    BlockKind,
    DocumentBlock,
    detect_mode,
    extract_features,
)
from docxtool.document.recognition.model import DocumentMode


def _authoritative_mode_for_title(title: str) -> DocumentMode:
    """构造具备标题证据的文首段，返回权威识别的文种。"""
    feature = extract_features(
        DocumentBlock(
            index=0,
            kind=BlockKind.PARAGRAPH,
            text=title,
            style_name="Title",
            alignment="center",
            bold=True,
            font_size_pt=22,
        )
    )
    return detect_mode([feature]).mode


def test_title_keyword_keeps_legacy_title_scorer_evidence() -> None:
    """标题关键词判断接收文本，返回旧 scorer 是否应放宽标题长度。"""
    assert has_title_keyword("2025年度民主生活会对照检查材料")
    assert has_title_keyword("在会议上的讲话稿")
    assert not has_title_keyword("2025年10月15日")


def test_doc_type_keyword_keeps_role_name_support_evidence() -> None:
    """文种关键词判断接收标题文本，返回是否支撑后续短署名行。"""
    assert has_doc_type_keyword("关于重点工作的通知")
    assert has_doc_type_keyword("年度工作总结")
    assert not has_doc_type_keyword("普通正文段落")


def test_report_heading_starts_match_legacy_report_cases() -> None:
    """报告标题起始判断接收去编号文本，返回是否为回顾类报告标题。"""
    assert starts_report_heading("一年来。测试正文")
    assert starts_report_heading("五年来，我们持续推进")
    assert not starts_report_heading("近年来，我们持续推进")


def test_report_heading_or_addressing_includes_common_salutations() -> None:
    """报告标题或称呼判断接收段落文本，返回是否应避开标题/加粗规则。"""
    assert starts_report_heading_or_addressing("一年来。测试正文")
    assert starts_report_heading_or_addressing("各位委员、同志们：")
    assert not starts_report_heading_or_addressing("普通正文")


def test_detect_legacy_doc_type_preserves_importer_mode_strings() -> None:
    """旧文种检测接收标题文本列表，返回 importer 兼容的文种字符串。"""
    assert detect_legacy_doc_type(["年度工作报告"]) == "REPORT"
    assert detect_legacy_doc_type(["工作回顾"]) == "REPORT"
    assert detect_legacy_doc_type(["情况报告"]) == "NORMAL"
    assert detect_legacy_doc_type(["会议通知"]) == "NORMAL"


def test_authoritative_report_mode_requires_work_report_or_review_title() -> None:
    """权威文种识别只将工作报告或工作回顾识别为报告模式。"""
    assert _authoritative_mode_for_title("年度工作报告") is DocumentMode.REPORT
    assert _authoritative_mode_for_title("年度工作回顾") is DocumentMode.REPORT
    assert _authoritative_mode_for_title("情况报告") is DocumentMode.UNKNOWN


def test_report_heading_score_returns_split_fact_and_score() -> None:
    """报告标题评分接收文本和编号前缀，返回候选分和是否拆分正文。"""
    assert legacy_report_heading_score("一年来。测试正文") == (95, True)
    assert legacy_report_heading_score("一、五年来。测试正文", "一、") == (95, True)
    assert legacy_report_heading_score("近年来。测试正文") == (0, False)


def test_title2_score_keeps_report_and_body_context_rules() -> None:
    """title2 评分接收文种和正文状态事实，返回旧 importer 候选分。"""
    assert legacy_title2_score(
        "名词解释",
        document_mode="REPORT",
        has_seen_body=False,
        previous_type="title",
        contains_colon=False,
        has_numbering=False,
    ) == 95
    assert legacy_title2_score(
        "工作安排",
        document_mode="NORMAL",
        has_seen_body=True,
        previous_type="body",
        contains_colon=False,
        has_numbering=False,
    ) == 95
    assert legacy_title2_score(
        "工作安排。",
        document_mode="NORMAL",
        has_seen_body=True,
        previous_type="body",
        contains_colon=False,
        has_numbering=False,
    ) == 0


def test_report_addressing_score_keeps_short_salutation_only() -> None:
    """报告称呼评分接收段落文本，返回短称呼候选分或 0。"""
    assert legacy_report_addressing_score("各位委员、同志们：") == 120
    assert legacy_report_addressing_score("各位委员、同志们：一年来我们持续推进重点工作并取得新的明显成效。") == 0
    assert legacy_report_addressing_score("同志们：") == 0


def test_glossary_title_score_requires_title2_and_keyword() -> None:
    """名词解释标题评分接收 title2 分值和文本，返回旧 importer 候选分。"""
    assert legacy_glossary_title_score("名词解释", title2_score=95) == 95
    assert legacy_glossary_title_score("注释", title2_score=95) == 95
    assert legacy_glossary_title_score("名词解释", title2_score=0) == 0
    assert legacy_glossary_title_score("普通标题", title2_score=95) == 0


def test_glossary_item_score_keeps_numbered_item_prefix_and_colon_meta() -> None:
    """名词解释条目评分接收编号和冒号事实，返回分值、meta 和原前缀。"""
    score, meta, prefix = legacy_glossary_item_score(
        "1.术语：解释内容",
        glossary_mode=True,
        numbering_type="heading3",
        prefix="1.",
        contains_colon=True,
    )
    assert score == 90
    assert meta == {"glossary_item": True, "colon_pos": 2}
    assert prefix == "1."


def test_glossary_item_score_supports_auto_numbered_colon_items() -> None:
    """名词解释条目评分接收无编号冒号文本，返回自动编号用的空前缀。"""
    assert legacy_glossary_item_score(
        "术语：解释内容",
        glossary_mode=True,
        numbering_type=None,
        prefix=None,
        contains_colon=True,
    ) == (90, {"glossary_item": True, "colon_pos": 2}, "")
    assert legacy_glossary_item_score(
        "术语",
        glossary_mode=True,
        numbering_type=None,
        prefix=None,
        contains_colon=False,
    ) == (0, {}, "")


def test_heading_addressing_score_requires_heading_before_body() -> None:
    """主送机关评分接收上一类型和正文状态，返回旧 importer 候选分。"""
    assert legacy_heading_addressing_score("各单位：", "heading1", has_seen_real_body=False) == 110
    assert legacy_heading_addressing_score("各单位：", "body", has_seen_real_body=False) == 0
    assert legacy_heading_addressing_score("各单位：", "heading1", has_seen_real_body=True) == 0
