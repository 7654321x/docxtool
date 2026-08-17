"""Filename, download header, and safe diagnostic helpers for the web layer."""

from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import quote


def safe_file_identifier(filename: str) -> str:
    """传入文件名文本，返回用于日志关联的 12 位 SHA-256 短标识。"""
    return hashlib.sha256(str(filename or "").encode("utf-8")).hexdigest()[:12]


def sanitize_internal_error_detail(value: object, limit: int = 500) -> str:
    """传入异常或诊断对象，返回去除密钥和本地路径后的有限长度文本。"""
    detail = str(value or "")
    detail = re.sub(
        r"(?i)\b(authorization|cookie|password|token|secret|api[_-]?key)\b\s*[:=]\s*[^\s,;]+",
        lambda match: f"{match.group(1)}=[redacted]",
        detail,
    )
    detail = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", detail)
    detail = re.sub(r"[A-Za-z]:[\\/][^\r\n\t\"'<>|]+", "[local-path]", detail)
    detail = re.sub(r"(?<!:)\/(?:[^\s/]+\/)+[^\s\"'<>|]*", "[local-path]", detail)
    return detail[: max(0, int(limit))]


def is_safe_uuid(value: str) -> bool:
    """传入字符串，返回它是否是可接受的 UUID 形态。"""
    return bool(re.match(r"^[0-9a-fA-F-]{32,36}$", value or ""))


def sanitize_filename(name: str) -> str:
    """传入原始文件名，返回适合 Windows 和下载响应使用的安全文件名。"""
    raw = str(name or "").replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    raw = raw.replace("\\", "/")
    raw = os.path.basename(raw) or raw
    raw = re.sub(r'[/\\:*?"<>|]+', "_", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" ._")
    if not raw or raw in {".", ".."}:
        raw = "download.docx"
    stem, ext = os.path.splitext(raw)
    if not stem:
        stem = "download"
    reserved = {
        "con", "prn", "aux", "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if stem.rstrip(" ._").lower() in reserved:
        stem = f"_{stem}"
    if not ext:
        ext = ".docx"
    cleaned = f"{stem}{ext}"
    return cleaned[:120]


def _sanitize_output_suffix(suffix: str) -> str:
    """传入自定义下载后缀，返回可安全拼接进文件名的后缀文本。"""
    cleaned = re.sub(r"[\x00-\x1f/\\:*?""<>|]+", "_", str(suffix or ""))
    cleaned = cleaned.strip(" .")
    if not cleaned:
        return ""
    if cleaned.lower().endswith(".docx"):
        cleaned = cleaned[: -len(".docx")].rstrip(" ._")
    return cleaned


def safe_download_filename(orig_name: str, output_suffix: str | None = None) -> str:
    """传入原始上传名和可选下载后缀，返回排版结果下载文件名。

    output_suffix 缺失、null、空字符串或纯空白时使用历史默认后缀
    ``_排版文件``；显式提供时追加在文件 stem 之后，最终固定为 .docx。
    """
    safe = sanitize_filename(orig_name)
    stem, _ext = os.path.splitext(safe)
    if not stem:
        stem = "download"
    suffix = _sanitize_output_suffix(output_suffix or "")
    if not suffix:
        return f"{stem}_排版文件.docx"
    return sanitize_filename(f"{stem}{suffix}.docx")


def content_disposition_filename(filename: str) -> str:
    """传入下载文件名，返回兼容 ASCII fallback 和 UTF-8 的响应头值。"""
    safe = sanitize_filename(filename)
    ascii_fallback = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        safe.encode("ascii", "ignore").decode("ascii"),
    ).strip("._-")
    if not ascii_fallback:
        ascii_fallback = "formatted.docx"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe, safe='')}"
