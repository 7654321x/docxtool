from __future__ import annotations

from docxtool.document.importer import _normalize_responsibility_line
from docxtool.document.normalization.responsibility import (
    is_responsibility_line,
    normalize_responsibility_line,
)


def test_responsibility_line_shape_is_generic() -> None:
    """验证责任单位行只依赖标签形态，不依赖具体单位名称。"""
    assert is_responsibility_line("责任单位：测试单位")
    assert is_responsibility_line("责 任 单 位：测试单位")
    assert is_responsibility_line("“责任单位：测试单位”")
    assert not is_responsibility_line("联系人：张三")


def test_responsibility_line_normalization_preserves_values() -> None:
    """验证责任单位规范化只处理标签和换行，不改写具体值。"""
    text = "“责 任 单 位：区政府责任单位：商务局”"

    assert normalize_responsibility_line(text) == "责任单位：区政府\n责任单位：商务局"
    assert _normalize_responsibility_line(text) == "责任单位：区政府\n责任单位：商务局"
