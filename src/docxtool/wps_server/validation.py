"""Strict input validation for the WPS public API."""

from __future__ import annotations

import re

_USERNAME_RE = re.compile(r"^[A-Za-z0-9]{5,32}$")
_PASSWORD_RE = re.compile(r"^[A-Za-z0-9]{5,64}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
_ERROR_CODE_RE = re.compile(r"^[A-Z0-9_]{0,100}$")
_APP_VERSION_RE = re.compile(r"^[A-Za-z0-9._+-]{1,40}$")
_NOTIFICATION_ID_RE = re.compile(r"^wnot_[A-Za-z0-9]{16,64}$")

WPS_NOTIFICATION_TITLE_MAX_CHARS = 120
WPS_NOTIFICATION_BODY_MAX_CHARS = 2_000
WPS_NOTIFICATION_BATCH_MAX = 20
WPS_NOTIFICATION_LEVELS = frozenset({"info", "warning", "error"})


class WpsValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


def require_object_fields(payload: dict, *, required, optional=()) -> None:
    """Require an exact JSON object field set."""
    if not isinstance(payload, dict):
        raise WpsValidationError("WPS_JSON_INVALID", "请求体必须是 JSON 对象")
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = required_set - set(payload)
    if missing:
        raise WpsValidationError("WPS_FIELD_REQUIRED", "缺少必填字段")
    if set(payload) - allowed:
        raise WpsValidationError("WPS_UNKNOWN_FIELD", "请求包含未知字段")


def validate_username(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or not 5 <= len(value) <= 32:
        raise WpsValidationError("USERNAME_LENGTH_INVALID", "账号必须为 5 至 32 位")
    if not _USERNAME_RE.fullmatch(value):
        raise WpsValidationError("USERNAME_CHARSET_INVALID", "账号只能包含英文字母和数字")
    if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
        raise WpsValidationError("USERNAME_COMPOSITION_INVALID", "账号必须同时包含字母和数字")
    return value, value.lower()


def validate_password(value: object) -> str:
    if not isinstance(value, str) or not 5 <= len(value) <= 64:
        raise WpsValidationError("PASSWORD_LENGTH_INVALID", "密码必须为 5 至 64 位")
    if not _PASSWORD_RE.fullmatch(value):
        raise WpsValidationError("PASSWORD_CHARSET_INVALID", "密码只能包含英文字母和数字")
    if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
        raise WpsValidationError("PASSWORD_COMPOSITION_INVALID", "密码必须同时包含字母和数字")
    return value


def validate_device_payload(value: object) -> dict:
    if not isinstance(value, dict):
        raise WpsValidationError("DEVICE_REQUIRED", "缺少设备信息")
    require_object_fields(
        value,
        required=("device_key", "device_name", "platform", "app_version"),
    )
    limits = {
        "device_key": 200,
        "device_name": 100,
        "platform": 40,
        "app_version": 40,
    }
    result = {}
    for field, maximum in limits.items():
        item = value[field]
        if not isinstance(item, str) or not item or item != item.strip() or len(item) > maximum:
            raise WpsValidationError("DEVICE_FIELD_INVALID", "设备信息字段无效")
        result[field] = item
    if not _APP_VERSION_RE.fullmatch(result["app_version"]):
        raise WpsValidationError("APP_VERSION_INVALID", "插件版本格式无效")
    return result


def validate_request_id(value: object) -> str:
    if not isinstance(value, str) or not _REQUEST_ID_RE.fullmatch(value):
        raise WpsValidationError("REQUEST_ID_INVALID", "排版请求编号无效")
    return value


def validate_app_version(value: object) -> str:
    if not isinstance(value, str) or not _APP_VERSION_RE.fullmatch(value):
        raise WpsValidationError("APP_VERSION_INVALID", "插件版本格式无效")
    return value


def validate_error_code(value: object) -> str:
    if not isinstance(value, str) or not _ERROR_CODE_RE.fullmatch(value):
        raise WpsValidationError("ERROR_CODE_INVALID", "错误代码格式无效")
    return value


def validate_notification_content(
    title: object,
    body: object,
    level: object,
) -> tuple[str, str, str]:
    """Normalize one administrator-authored, plain-text notification payload."""
    if not isinstance(title, str):
        raise WpsValidationError("WPS_NOTIFICATION_TITLE_INVALID", "通知标题无效")
    normalized_title = title.strip()
    if not normalized_title or len(normalized_title) > WPS_NOTIFICATION_TITLE_MAX_CHARS:
        raise WpsValidationError("WPS_NOTIFICATION_TITLE_INVALID", "通知标题无效")
    if not isinstance(body, str):
        raise WpsValidationError("WPS_NOTIFICATION_BODY_INVALID", "通知正文无效")
    normalized_body = body.strip()
    if not normalized_body or len(normalized_body) > WPS_NOTIFICATION_BODY_MAX_CHARS:
        raise WpsValidationError("WPS_NOTIFICATION_BODY_INVALID", "通知正文无效")
    if not isinstance(level, str) or level not in WPS_NOTIFICATION_LEVELS:
        raise WpsValidationError("WPS_NOTIFICATION_LEVEL_INVALID", "通知级别无效")
    return normalized_title, normalized_body, level


def validate_notification_ids(value: object) -> list[str]:
    """Validate and de-duplicate a bounded acknowledgement batch."""
    if not isinstance(value, list) or not value or len(value) > WPS_NOTIFICATION_BATCH_MAX:
        raise WpsValidationError("WPS_NOTIFICATION_IDS_INVALID", "通知确认编号无效")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not _NOTIFICATION_ID_RE.fullmatch(item):
            raise WpsValidationError("WPS_NOTIFICATION_IDS_INVALID", "通知确认编号无效")
        if item not in seen:
            seen.add(item)
            normalized.append(item)
    return normalized
