from docxtool.document.engine.punctuation import find_protected_spans, normalize_punctuation, normalize_punctuation_text


def test_normalizes_chinese_context_punctuation_without_spacing_changes() -> None:
    text = '他说"你好,世界..."--结束(重要)! 下一句:继续;可以吗?'

    normalized = normalize_punctuation_text(text)

    assert normalized == "他说“你好，世界……”——结束（重要）！ 下一句：继续；可以吗？"
    assert "！ " in normalized


def test_off_mode_returns_input_unchanged() -> None:
    text = '他说"你好,世界..."'

    assert normalize_punctuation_text(text, mode="off") == text


def test_normalization_is_idempotent() -> None:
    text = '他说"你好,世界..."--结束(重要)!'
    once = normalize_punctuation_text(text)

    assert normalize_punctuation_text(once) == once


def test_first_version_does_not_convert_straight_single_quotes() -> None:
    text = "他说'你好,世界.'"

    assert normalize_punctuation_text(text) == "他说'你好，世界。'"


def test_protects_technical_spans() -> None:
    text = (
        "访问 https://example.com/a,b?x=1.2 和 admin@example.com, "
        "IP 192.168.1.1:8080, IPv6 fe80::1, 域名 example.com:443, "
        "路径 C:\\Temp\\a,b.txt 与 /usr/local/bin, 时间 12:30, "
        "版本 1.2.3, 文件 report.docx, 标准 GB/T 7714-2015, 缩写 U.S.A.。"
    )

    result = normalize_punctuation(text)

    assert "https://example.com/a,b?x=1.2" in result.text
    assert "admin@example.com" in result.text
    assert "192.168.1.1:8080" in result.text
    assert "fe80::1" in result.text
    assert "example.com:443" in result.text
    assert "C:\\Temp\\a,b.txt" in result.text
    assert "/usr/local/bin" in result.text
    assert "12:30" in result.text
    assert "1.2.3" in result.text
    assert "report.docx" in result.text
    assert "GB/T 7714-2015" in result.text
    assert "U.S.A." in result.text
    assert any(span.kind == "url" for span in result.protected_spans)
    assert any(span.kind == "email" for span in result.protected_spans)


def test_find_protected_spans_reports_boundaries() -> None:
    text = "中文 example.com:8080, 时间 08:30."

    spans = find_protected_spans(text)

    assert ("domain", "example.com:8080") in {(span.kind, span.text) for span in spans}
    assert ("time", "08:30") in {(span.kind, span.text) for span in spans}
