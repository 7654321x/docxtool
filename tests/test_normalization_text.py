from docxtool.document.normalization.text import (
    normalize_basic_text,
    normalize_legacy_punctuation_text,
    normalize_quotes,
    to_chinese_punctuation,
)


def test_normalize_basic_text_converts_chinese_parentheses_and_spaces() -> None:
    """基础文本清理应只处理中文括号和不可见空白。"""
    assert normalize_basic_text("测试(内容)\u3000\u200b结束") == "测试（内容）结束"
    assert normalize_basic_text("abc(test)") == "abc(test)"


def test_legacy_punctuation_keeps_broken_heading_dot() -> None:
    """旧兼容标点转换应保留中文一级编号中的损坏点号。"""
    assert to_chinese_punctuation("二.标题") == "二.标题"
    assert to_chinese_punctuation("正文,测试.") == "正文，测试。"


def test_legacy_punctuation_preserves_space_after_colon() -> None:
    assert to_chinese_punctuation("标题: 正文") == "标题： 正文"


def test_normalize_quotes_preserves_english_apostrophes() -> None:
    """引号转换应处理中文语境，同时保留英文单词内部撇号。"""
    assert normalize_quotes('"你好"') == "“你好”"
    assert normalize_quotes("O'Reilly don't '中文'") == "O'Reilly don't ‘中文’"


def test_legacy_punctuation_text_runs_existing_order() -> None:
    """完整旧文本规范化应按基础清理、引号、标点顺序执行。"""
    assert normalize_legacy_punctuation_text('"你好,世界."(重要)') == "“你好，世界。”（重要）"
