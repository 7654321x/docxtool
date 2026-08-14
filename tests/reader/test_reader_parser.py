from apps.reader.parser import normalize_newlines, parse_chapters


def test_parser_recognizes_chinese_and_english_chapters_in_source_order():
    text = "第一章 开始\r\n内容\n第12回 继续\n内容\nCHAPTER 3 Final\n结尾"

    chapters = parse_chapters(normalize_newlines(text), "book")

    assert [chapter.title for chapter in chapters] == [
        "第一章 开始",
        "第12回 继续",
        "CHAPTER 3 Final",
    ]
    assert chapters[0].start_offset == 0
    assert chapters[0].end_offset == chapters[1].start_offset
    assert chapters[-1].end_offset == len(normalize_newlines(text))


def test_parser_keeps_unchaptered_text_as_one_neutral_full_text_block():
    text = "普通段落\n\n没有章节标题。"

    chapters = parse_chapters(text, "book")

    assert [(chapter.title, chapter.start_offset, chapter.end_offset) for chapter in chapters] == [
        ("全文", 0, len(text))
    ]


def test_parser_keeps_visible_leading_text_before_the_first_chapter():
    text = "导语内容\n\n第一章 开始\n正文"

    chapters = parse_chapters(text, "book")

    assert [(chapter.title, chapter.start_offset, chapter.end_offset) for chapter in chapters] == [
        ("前置内容", 0, text.index("第一章")),
        ("第一章 开始", text.index("第一章"), len(text)),
    ]
