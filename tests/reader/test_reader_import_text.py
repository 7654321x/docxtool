import pytest

from apps.reader.import_text import TextImportError, decode_text


def test_decode_text_supports_utf8_bom_and_gb18030():
    assert decode_text("第一章".encode("utf-8")) == ("第一章", "utf-8")
    assert decode_text(b"\xef\xbb\xbf" + "第一章".encode("utf-8")) == ("第一章", "utf-8-sig")
    assert decode_text("第一章".encode("gb18030")) == ("第一章", "gb18030")


def test_decode_text_rejects_empty_or_unsupported_bytes():
    with pytest.raises(TextImportError, match="READER_FILE_EMPTY"):
        decode_text(b"")
    with pytest.raises(TextImportError, match="READER_ENCODING_UNSUPPORTED"):
        decode_text(b"\x81")
