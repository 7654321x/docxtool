from docxtool.document.engine.render_text import (
    attachment_item_wrap_start_chars,
    attachment_note_wrap_start_chars,
    strip_heading_numbering,
)


def test_attachment_note_wrap_start_chars_handles_numbered_and_plain_notes() -> None:
    assert attachment_note_wrap_start_chars("附件：材料") == 5
    assert attachment_note_wrap_start_chars("附件：1. 材料") == 8
    assert attachment_note_wrap_start_chars("附件：12、材料") == 9


def test_attachment_item_wrap_start_chars_aligns_after_item_number() -> None:
    assert attachment_item_wrap_start_chars("材料") == 8
    assert attachment_item_wrap_start_chars("1. 材料") == 8
    assert attachment_item_wrap_start_chars("12、材料") == 9


def test_strip_heading_numbering_removes_only_leading_heading_tokens() -> None:
    assert strip_heading_numbering("一、标题") == "标题"
    assert strip_heading_numbering("（一）标题") == "标题"
    assert strip_heading_numbering("3..标题") == "标题"
    assert strip_heading_numbering("正文中的一、不是段首") == "正文中的一、不是段首"
