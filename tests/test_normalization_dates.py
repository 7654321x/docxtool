from docxtool.document.normalization.dates import (
    chinese_number_to_int,
    chinese_year_to_int,
    is_attachment_page_mark,
    is_sign_date_text,
    normalize_attachment_page_mark,
    normalize_sign_date,
)


def test_chinese_number_helpers_keep_existing_date_shapes() -> None:
    """数字 helper 应兼容阿拉伯数字和简单中文数字。"""
    assert chinese_number_to_int("十") == 10
    assert chinese_number_to_int("二十五") == 25
    assert chinese_number_to_int("15") == 15
    assert chinese_number_to_int("测试") is None
    assert chinese_year_to_int("二零二六") == 2026
    assert chinese_year_to_int("2026") == 2026


def test_sign_date_normalization_is_shared_by_importer_and_tail() -> None:
    """成文日期规范化应只转换可靠日期，普通文本保持原样。"""
    assert is_sign_date_text("二零二六年十月十五日")
    assert normalize_sign_date("二零二六年十月十五日") == "2026年10月15日"
    assert normalize_sign_date("2026年10月15日") == "2026年10月15日"
    assert not is_sign_date_text("2026年10月15日会议")
    assert normalize_sign_date("2026年10月15日会议") == "2026年10月15日会议"


def test_attachment_page_mark_normalization_is_shared_by_importer_and_tail() -> None:
    """附件页标识规范化应统一输出附件和数字序号。"""
    assert is_attachment_page_mark("附件一")
    assert is_attachment_page_mark("附件 12")
    assert normalize_attachment_page_mark("附件一") == "附件 1"
    assert normalize_attachment_page_mark("附件") == "附件"
    assert normalize_attachment_page_mark("附件材料") == "附件材料"
