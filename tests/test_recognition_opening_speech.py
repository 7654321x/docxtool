from __future__ import annotations

from types import SimpleNamespace

from docxtool.document.importer import (
    _opening_speech_title_text,
    _strip_inferred_speech_numbering,
)
from docxtool.document.recognition.opening_speech import (
    opening_speech_title_text,
    strip_inferred_speech_numbering,
)


def _contains_colon(text: str) -> bool:
    """测试辅助：传入文本，返回是否含中英文冒号。"""
    return "：" in text or ":" in text


def _match_numbering(text: str) -> tuple[str | None, str]:
    """测试辅助：传入文本，返回简化的一级编号匹配结果。"""
    if (text or "").startswith("一、"):
        return "heading1", "一、"
    return None, ""


def test_opening_speech_title_detects_first_line_without_keywords_list() -> None:
    """验证文首讲话标题 helper 只输出候选证据，不依赖 importer 上下文对象。"""
    title = "在区政协九届一次会议闭幕大会上的讲话"

    assert opening_speech_title_text(
        title,
        has_seen_body=False,
        previous_type_id="",
        contains_colon_func=_contains_colon,
        match_numbering_func=_match_numbering,
    ) == title


def test_opening_speech_title_strips_inferred_heading_numbering() -> None:
    """验证误带中文一级编号的文首讲话标题可返回干净标题文本。"""
    text = "一、在区政协九届一次会议闭幕大会上的讲话"

    assert opening_speech_title_text(
        text,
        has_seen_body=False,
        previous_type_id="",
        contains_colon_func=_contains_colon,
        match_numbering_func=_match_numbering,
    ) == "在区政协九届一次会议闭幕大会上的讲话"
    assert strip_inferred_speech_numbering(
        text,
        match_numbering_func=_match_numbering,
    ) == "在区政协九届一次会议闭幕大会上的讲话"


def test_opening_speech_title_rejects_body_context_and_colon_lines() -> None:
    """验证正文已开始或含冒号时，不把普通段落升级为讲话主标题。"""
    title = "在区政协九届一次会议闭幕大会上的讲话"

    assert opening_speech_title_text(
        title,
        has_seen_body=True,
        previous_type_id="body",
        contains_colon_func=_contains_colon,
        match_numbering_func=_match_numbering,
    ) is None
    assert opening_speech_title_text(
        f"{title}：说明",
        has_seen_body=False,
        previous_type_id="",
        contains_colon_func=_contains_colon,
        match_numbering_func=_match_numbering,
    ) is None


def test_importer_opening_speech_facade_keeps_legacy_context_shape() -> None:
    """验证 importer 旧私有入口仍接受旧 DetectionContext 形态。"""
    ctx = SimpleNamespace(has_seen_body=False, prev_type_id="")
    text = "一、在区政协九届一次会议闭幕大会上的讲话"

    assert _opening_speech_title_text(text, ctx) == "在区政协九届一次会议闭幕大会上的讲话"
    assert _strip_inferred_speech_numbering(text) == "在区政协九届一次会议闭幕大会上的讲话"
