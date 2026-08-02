from __future__ import annotations

from docxtool.document.recognition.front_matter import (
    legacy_author_line_score,
    legacy_date_line_score,
    legacy_role_name_score,
    legacy_title_cont_score,
    legacy_title_score,
)


def test_title_score_keeps_first_front_matter_title() -> None:
    """主标题评分接收文首事实，返回旧 importer 主标题候选分。"""
    assert legacy_title_score(
        "年度工作总结",
        None,
        has_seen_body=False,
        contains_colon=False,
        has_numbering=False,
    ) == 100


def test_title_score_rejects_body_previous_type_numbering_and_colon() -> None:
    """主标题评分接收正文、上一类型、编号和冒号事实，返回不能作为标题的 0 分。"""
    assert legacy_title_score("年度工作总结", None, has_seen_body=True, contains_colon=False, has_numbering=False) == 0
    assert legacy_title_score("年度工作总结", "title", has_seen_body=False, contains_colon=False, has_numbering=False) == 0
    assert legacy_title_score("一、年度工作总结", None, has_seen_body=False, contains_colon=False, has_numbering=True) == 0
    assert legacy_title_score("主题：工作总结", None, has_seen_body=False, contains_colon=True, has_numbering=False) == 0


def test_title_cont_score_keeps_short_front_matter_continuation() -> None:
    """标题续行评分接收上一结构事实，返回旧 importer 标题续行候选分。"""
    assert legacy_title_cont_score(
        "对照检查材料",
        "title",
        has_seen_body=False,
        contains_colon=False,
        has_numbering=False,
    ) == 90
    assert legacy_title_cont_score(
        "2025年度民主生活会",
        "title",
        has_seen_body=False,
        contains_colon=False,
        has_numbering=False,
    ) == 90


def test_title_cont_score_rejects_date_colon_and_spaced_name() -> None:
    """标题续行评分接收日期、冒号和连续空格事实，返回不能作为续行的 0 分。"""
    assert legacy_title_cont_score("2025年10月15日", "title", has_seen_body=False, contains_colon=False, has_numbering=False) == 0
    assert legacy_title_cont_score("主题：材料", "title", has_seen_body=False, contains_colon=True, has_numbering=False) == 0
    assert legacy_title_cont_score("办公室主任  张三", "title", has_seen_body=False, contains_colon=False, has_numbering=False) == 0


def test_date_line_score_keeps_header_date_evidence() -> None:
    """日期行评分接收文本和上下文事实，返回旧 importer 日期行候选分。"""
    assert legacy_date_line_score("（2025年10月15日）", "title", has_seen_body=False, has_numbering=False) == 85
    assert legacy_date_line_score("2025年10月15日", "role_name", has_seen_body=False, has_numbering=False) == 85


def test_date_line_score_rejects_body_numbering_and_title_keyword() -> None:
    """日期行评分接收正文/编号/标题关键词事实，返回不能作为日期行的 0 分。"""
    assert legacy_date_line_score("2025年10月15日", "title", has_seen_body=True, has_numbering=False) == 0
    assert legacy_date_line_score("2025年度民主生活会对照检查材料", "title", has_seen_body=False, has_numbering=False) == 0
    assert legacy_date_line_score("2025年10月15日", "title", has_seen_body=False, has_numbering=True) == 0


def test_author_line_score_keeps_date_following_short_name() -> None:
    """署名行评分接收日期行后的短文本，返回旧 importer 署名行候选分。"""
    assert legacy_author_line_score(
        "张三",
        "date_line",
        has_seen_body=False,
        contains_colon=False,
        has_numbering=False,
    ) == 80


def test_author_line_score_rejects_structural_conflicts() -> None:
    """署名行评分接收冒号、编号和连续空格事实，返回不能作为署名行的 0 分。"""
    assert legacy_author_line_score("张三", "title", has_seen_body=False, contains_colon=False, has_numbering=False) == 0
    assert legacy_author_line_score("张三：", "date_line", has_seen_body=False, contains_colon=True, has_numbering=False) == 0
    assert legacy_author_line_score("张  三", "date_line", has_seen_body=False, contains_colon=False, has_numbering=False) == 0


def test_role_name_score_keeps_double_space_name_shape() -> None:
    """职务姓名评分接收当前短行和标题，返回连续空格姓名形态的旧分值。"""
    assert legacy_role_name_score("区政协党组书记、主席  张三", "", contains_colon=False) == 80


def test_role_name_score_prefers_role_keyword_with_name() -> None:
    """职务姓名评分接收职务关键词短行，返回高于标题续行的旧分值。"""
    assert legacy_role_name_score("测试办公室主任 张测试", "", contains_colon=False) == 110


def test_role_name_score_uses_speech_title_for_bare_name() -> None:
    """职务姓名评分接收上一标题，返回讲话类标题后裸姓名的旧分值。"""
    assert legacy_role_name_score("张三", "在闭幕大会上的讲话", contains_colon=False) == 92
    assert legacy_role_name_score("测试办公室主任", "在闭幕大会上的讲话", contains_colon=False) == 95


def test_role_name_score_uses_document_type_title_as_weak_support() -> None:
    """职务姓名评分接收文种标题，返回文种标题后短署名的弱候选分。"""
    assert legacy_role_name_score("张三", "年度工作报告", contains_colon=False) == 75
    assert legacy_role_name_score("张三", "普通标题", contains_colon=False) == 0


def test_role_name_score_rejects_colon_and_long_non_name_line() -> None:
    """职务姓名评分接收冒号事实和长文本，返回不能作为 role_name 的 0 分。"""
    assert legacy_role_name_score("责任单位：办公室", "年度工作报告", contains_colon=True) == 0
    assert legacy_role_name_score(
        "这是一段明显超过长度限制的普通正文内容并且继续延长",
        "年度工作报告",
        contains_colon=False,
    ) == 0
