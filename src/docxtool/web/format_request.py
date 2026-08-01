"""Format-configuration request parsing helpers for upload endpoints."""

from __future__ import annotations

import base64
import binascii
import json
from urllib.parse import unquote

from docxtool.document.style_config import ConfigValidationError, validate_format_config


class FormatConfigRequestError(ValueError):
    """Request-level format config error carrying a stable code and safe details."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: str = "",
        reason: str = "",
        status: int = 400,
    ):
        """Store stable error data from code/message inputs and expose it as ValueError."""
        self.code = code
        self.message = message
        self.field = field
        self.reason = reason
        self.status = status
        super().__init__(f"{code}: {message}")


def format_config_error(code: str, message: str, *, field: str = "", reason: str = "") -> FormatConfigRequestError:
    """Build a format-config request error from a stable code and safe message."""
    return FormatConfigRequestError(
        code,
        message,
        field=field,
        reason=reason,
        status=413 if code == "FORMAT_CONFIG_TOO_LARGE" else 400,
    )


def decode_format_config(
    headers,
    *,
    max_header_bytes: int,
    max_json_bytes: int,
) -> dict | None:
    """Decode X-Format-Config headers, validate the config object and return it."""
    raw = headers.get("X-Format-Config", "") if headers else ""
    if not raw:
        return None
    encoding = (headers.get("X-Format-Config-Encoding", "") if headers else "").strip().lower()
    if len(raw.encode("ascii", "ignore")) > max_header_bytes:
        raise format_config_error("FORMAT_CONFIG_TOO_LARGE", "配置请求头过大", reason="配置请求头过大")
    if encoding != "base64url-json":
        raise format_config_error("FORMAT_CONFIG_INVALID", "不支持的配置编码", reason="不支持的配置编码")
    try:
        padding = "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode((raw + padding).encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise format_config_error("FORMAT_CONFIG_INVALID", "配置解码失败", reason="配置解码失败") from exc
    if len(decoded) > max_json_bytes:
        raise format_config_error("FORMAT_CONFIG_TOO_LARGE", "配置内容过大", reason="配置内容过大")
    try:
        config = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise format_config_error("FORMAT_CONFIG_INVALID", "配置 JSON 无效", reason="配置 JSON 无效") from exc
    if not isinstance(config, dict):
        raise format_config_error("FORMAT_CONFIG_INVALID", "配置必须是 JSON 对象", reason="配置必须是 JSON 对象")
    if "styles" not in config or "page" not in config:
        raise format_config_error("FORMAT_CONFIG_INVALID", "配置缺少 styles 或 page", reason="配置缺少 styles 或 page")
    try:
        return validate_format_config(config)
    except ConfigValidationError as exc:
        field = getattr(exc, "field", "")
        reason = getattr(exc, "reason", "") or "配置无效"
        message = f"{field}: {reason}" if field else reason
        raise format_config_error(exc.code, message, field=field, reason=reason) from exc
    except ValueError as exc:
        raise format_config_error("FORMAT_CONFIG_INVALID", "配置无效", reason="配置无效") from exc


def upload_request_meta(headers) -> dict:
    """Read upload metadata headers and return normalized request metadata."""
    return {
        "processing_mode": headers.get("X-Processing-Mode", "smart") if headers else "smart",
        "preset_id": headers.get("X-Preset-Id", "") if headers else "",
        "preset_name": unquote(headers.get("X-Preset-Name", "")) if headers else "",
        "template_type": headers.get("X-Template-Type", "") if headers else "",
    }


def processing_strategy_from_mode(value: object) -> str:
    """Map an external processing mode value to the internal strategy string."""
    mode = str(value or "").strip().lower()
    if not mode:
        return ""
    strategy = {
        "smart": "structural",
        "structural": "structural",
        "strict": "strict",
        "normalize": "normalize",
    }.get(mode)
    if not strategy:
        raise format_config_error(
            "PROCESSING_MODE_INVALID",
            "处理模式仅支持 smart、structural、strict 或 normalize",
            field="X-Processing-Mode",
            reason="处理模式无效",
        )
    return strategy


def validate_requested_processing_mode(format_config: dict | None, request_meta: dict) -> None:
    """Validate mode headers against format config and write processing_strategy into metadata."""
    requested = processing_strategy_from_mode(request_meta.get("processing_mode", ""))
    request_meta["processing_strategy"] = requested or "structural"
    if not isinstance(format_config, dict):
        return
    processing = format_config.get("processing", {})
    configured = str(processing.get("strategy", "") if isinstance(processing, dict) else "")
    if configured and requested and configured != requested:
        raise format_config_error(
            "PROCESSING_MODE_CONFLICT",
            "X-Processing-Mode 与排版配置中的处理模式不一致",
            field="X-Processing-Mode",
            reason="处理模式冲突",
        )
