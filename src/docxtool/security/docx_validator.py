"""DOCX upload validation helpers.

The validator rejects malformed OOXML archives before they reach python-docx.
It is intentionally conservative: the service only needs normal .docx files,
so nested archives and suspicious member paths are rejected early.
"""

from __future__ import annotations

import os
import posixpath
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_XML_SUFFIXES = (".xml", ".rels", ".vml")
_NESTED_ARCHIVE_SUFFIXES = (".zip", ".docx", ".pptx", ".xlsx", ".xlsm", ".jar", ".7z", ".rar")
_COMPLEX_XML_MARKERS = {
    "wp:anchor": "浮动图片",
    "w:txbxcontent": "文本框",
    "v:textbox": "文本框",
    "w:object": "嵌入对象",
    "o:oleobject": "OLE 对象",
    "mc:alternatecontent": "兼容性内容",
    "w:commentrangestart": "批注",
    "w:footnotereference": "脚注",
    "w:endnotereference": "尾注",
    "w:fldsimple": "域代码",
    "w:hyperlink": "外部链接",
}


@dataclass
class DocxValidationError(Exception):
    code: str
    message: str
    status: int = 400

    def __str__(self) -> str:  # pragma: no cover - Exception protocol
        return self.message


def _reject(code: str, message: str, status: int = 400) -> None:
    raise DocxValidationError(code=code, message=message, status=status)


def _open_docx_archive(source: str | os.PathLike | BytesIO) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise DocxValidationError(code="INVALID_DOCX", message="无效的 ZIP / DOCX 文件") from exc
    except zipfile.LargeZipFile as exc:
        raise DocxValidationError(code="INVALID_DOCX", message="DOCX 文件过大，无法打开") from exc


def _is_absolute_member(name: str) -> bool:
    if name.startswith("/"):
        return True
    if re.match(r"^[A-Za-z]:", name):
        return True
    return False


def _normalized_member_name(name: str) -> str:
    name = (name or "").replace("\\", "/").strip()
    if not name:
        _reject("INVALID_DOCX", "DOCX 文件结构异常：存在空路径成员")
    if _CONTROL_CHAR_RE.search(name):
        _reject("INVALID_DOCX", "DOCX 文件结构异常：包含非法控制字符")
    if _is_absolute_member(name):
        _reject("INVALID_DOCX", f"DOCX 文件结构异常：非法路径 {name!r}")

    normalized = posixpath.normpath(name)
    if normalized in ("", ".", ".."):
        _reject("INVALID_DOCX", f"DOCX 文件结构异常：非法路径 {name!r}")
    if normalized.startswith("../") or "/../" in f"/{normalized}/":
        _reject("INVALID_DOCX", f"DOCX 文件结构异常：非法路径 {name!r}")
    return normalized


def _is_xml_member(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(_XML_SUFFIXES) or lower == "[content_types].xml"


def _is_media_member(name: str) -> bool:
    lower = name.lower()
    return lower.startswith("word/media/") or lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".wmf", ".emf", ".svg"))


def _looks_like_nested_archive(name: str) -> bool:
    return name.lower().endswith(_NESTED_ARCHIVE_SUFFIXES)


def validate_docx_upload(
    data: bytes | str | os.PathLike,
    *,
    max_upload_bytes: int,
    max_uncompressed_bytes: int,
    max_file_count: int,
    max_xml_bytes: int,
    max_media_bytes: int,
    max_compression_ratio: int,
) -> None:
    """Validate an uploaded DOCX archive.

    Raises DocxValidationError with a stable code and human-readable message.
    """
    if isinstance(data, (str, os.PathLike)):
        path = os.fspath(data)
        if not path or not os.path.exists(path):
            _reject("INVALID_DOCX", "文件为空或不是有效的 DOCX")
        if os.path.getsize(path) > max_upload_bytes:
            _reject("FILE_TOO_LARGE", "文件过大", 413)
        archive = _open_docx_archive(path)
    else:
        if not data:
            _reject("INVALID_DOCX", "文件为空或不是有效的 DOCX")
        if len(data) > max_upload_bytes:
            _reject("FILE_TOO_LARGE", "文件过大", 413)
        archive = _open_docx_archive(BytesIO(data))
    try:
        with archive as zf:
            infos = zf.infolist()
            if not infos:
                _reject("INVALID_DOCX", "DOCX 文件为空或结构损坏")
            if len(infos) > max_file_count:
                _reject("INVALID_DOCX", "DOCX 文件内成员过多，疑似压缩炸弹")

            required = {"[Content_Types].xml", "word/document.xml", "_rels/.rels"}
            seen = set()
            total_uncompressed = 0
            total_compressed = 0

            for info in infos:
                name = _normalized_member_name(info.filename)
                if info.is_dir():
                    continue

                seen.add(name)
                total_uncompressed += int(info.file_size or 0)
                total_compressed += max(int(info.compress_size or 0), 0)
                if total_uncompressed > max_uncompressed_bytes:
                    _reject("INVALID_DOCX", "DOCX 解压后内容过大，疑似压缩炸弹")

                if total_compressed > 0 and total_uncompressed / max(total_compressed, 1) > max_compression_ratio:
                    _reject("INVALID_DOCX", "DOCX 压缩比异常，疑似压缩炸弹")
                if info.compress_size == 0 and info.file_size > 0 and info.file_size > max_xml_bytes:
                    _reject("INVALID_DOCX", "DOCX 压缩比异常，疑似压缩炸弹")

                if _looks_like_nested_archive(name):
                    _reject("INVALID_DOCX", f"DOCX 文件包含嵌套压缩内容: {name}")
                if _is_xml_member(name) and info.file_size > max_xml_bytes:
                    _reject("INVALID_DOCX", f"XML 文件过大: {name}")
                if _is_media_member(name) and info.file_size > max_media_bytes:
                    _reject("INVALID_DOCX", f"媒体文件过大: {name}")

            if not required.issubset(seen):
                missing = ", ".join(sorted(required - seen))
                _reject("INVALID_DOCX", f"DOCX 缺少必要文件: {missing}")

            bad_member = zf.testzip()
            if bad_member:
                _reject("INVALID_DOCX", f"DOCX 文件损坏: {bad_member}")
    except zipfile.BadZipFile as exc:
        raise DocxValidationError(code="INVALID_DOCX", message="无效的 ZIP / DOCX 文件") from exc
    except zipfile.LargeZipFile as exc:
        raise DocxValidationError(code="INVALID_DOCX", message="DOCX 文件过大，无法打开") from exc


def detect_docx_complexity(
    data: bytes | str | os.PathLike,
) -> list[str]:
    """Return conservative user-facing warnings for complex Word features.

    The detector does not block uploads. It only reports content that this
    service may not preserve perfectly during reconstruction.
    """
    if isinstance(data, (str, os.PathLike)):
        path = os.fspath(data)
        if not path or not os.path.exists(path):
            return []
        try:
            archive = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, zipfile.LargeZipFile):
            return []
    else:
        if not data:
            return []
        try:
            archive = zipfile.ZipFile(BytesIO(data))
        except (zipfile.BadZipFile, zipfile.LargeZipFile):
            return []

    warnings: list[str] = []
    try:
        with archive as zf:
            names = {_normalized_member_name(info.filename).lower() for info in zf.infolist() if not info.is_dir()}
            if any(name.startswith("word/header") and name.endswith(".xml") for name in names):
                warnings.append("文档包含页眉，排版结果可能无法完整保留")
            if any(name.startswith("word/footer") and name.endswith(".xml") for name in names):
                warnings.append("文档包含页脚或页码，排版结果可能无法完整保留")
            if "word/footnotes.xml" in names:
                warnings.append("文档包含脚注，排版结果可能无法完整保留")
            if "word/endnotes.xml" in names:
                warnings.append("文档包含尾注，排版结果可能无法完整保留")
            if "word/comments.xml" in names:
                warnings.append("文档包含批注，排版结果可能无法完整保留")
            if any(name.startswith("word/embeddings/") for name in names):
                warnings.append("文档包含嵌入对象，排版结果可能无法完整保留")
            if any(name.startswith("word/diagrams/") for name in names):
                warnings.append("文档包含 SmartArt 或图示对象，排版结果可能无法完整保留")
            if any(name.startswith("word/media/") for name in names):
                warnings.append("文档包含图片，复杂浮动或环绕布局可能无法完整保留")

            xml_sources = []
            for candidate in ("word/document.xml", "word/_rels/document.xml.rels"):
                try:
                    xml_sources.append(zf.read(candidate).decode("utf-8", errors="ignore").lower())
                except Exception:
                    continue
            xml_blob = "\n".join(xml_sources)
            for marker, label in _COMPLEX_XML_MARKERS.items():
                if marker in xml_blob:
                    if label == "外部链接":
                        warnings.append("文档包含链接或域代码，排版结果可能无法完整保留")
                    else:
                        warnings.append(f"文档包含{label}，排版结果可能无法完整保留")

    except (zipfile.BadZipFile, zipfile.LargeZipFile):
        return []

    unique: list[str] = []
    seen = set()
    for item in warnings:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique
