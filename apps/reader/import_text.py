"""Decode TXT bytes using the supported local-reader encoding contract."""

from __future__ import annotations


class TextImportError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def decode_text(raw: bytes) -> tuple[str, str]:
    if not raw:
        raise TextImportError("READER_FILE_EMPTY")
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeDecodeError as exc:
            raise TextImportError("READER_ENCODING_UNSUPPORTED") from exc
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        try:
            return raw.decode("gb18030"), "gb18030"
        except UnicodeDecodeError as exc:
            raise TextImportError("READER_ENCODING_UNSUPPORTED") from exc
