"""Validation and identity helpers shared by the HTTP layer."""

import unicodedata


def normalize_username(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def validate_username(value: str) -> tuple[str, str]:
    display = unicodedata.normalize("NFKC", str(value or "")).strip()
    normalized = display.casefold()
    if not 3 <= len(normalized) <= 32:
        raise ValueError("USERNAME_INVALID:用户名长度必须为 3 至 32 个字符")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in normalized):
        raise ValueError("USERNAME_INVALID:用户名不能包含控制字符")
    return display, normalized


def validate_password(value: str) -> str:
    password = str(value or "")
    if not 8 <= len(password) <= 128:
        raise ValueError("PASSWORD_INVALID:密码长度必须为 8 至 128 个字符")
    return password
