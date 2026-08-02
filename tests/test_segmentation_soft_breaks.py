from __future__ import annotations

from docxtool.document.segmentation.soft_breaks import (
    is_header_role_date_pair,
    is_dispatch_number_line,
    is_role_name_line,
)


def test_role_name_line_uses_shape_and_title_evidence_without_name_list() -> None:
    """验证职务姓名拆段证据依赖形态和职务词，不依赖具体人名名单。"""
    assert is_role_name_line("区政协党组书记、主席  张三")
    assert is_role_name_line("办公室主任  李四")
    assert is_role_name_line("政协主席  王五")
    assert not is_role_name_line("这是普通正文内容，没有连续空格。")
    assert not is_role_name_line("责任单位：办公室")


def test_header_role_date_pair_detects_adjacent_header_lines() -> None:
    """验证文首职务姓名和括号日期组合可作为软换行拆段事实。"""
    assert is_header_role_date_pair("区政协党组书记、主席  张三", "（2026年8月2日）")
    assert is_header_role_date_pair("办公室主任  李四", "(2026年8月2日)")
    assert not is_header_role_date_pair("普通正文", "（2026年8月2日）")
    assert not is_header_role_date_pair("区政协党组书记、主席  张三", "2026年8月2日")


def test_dispatch_number_line_ignores_internal_spaces() -> None:
    """验证结构化发文字号行可作为软换行边界事实。"""
    assert is_dispatch_number_line("内政协发〔2026〕12号")
    assert is_dispatch_number_line("内政协发〔2026〕 12 号")
    assert not is_dispatch_number_line("关于内政协发〔2026〕12号文件的说明")
