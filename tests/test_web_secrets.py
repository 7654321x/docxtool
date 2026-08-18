from __future__ import annotations

import pytest

from docxtool.web.secrets import (
    DEFAULT_ADMIN_TOKEN,
    DEFAULT_PROXY_SECRET,
    load_secret,
    validate_environment_secrets,
    validate_required_secrets,
)


def test_load_secret_reads_environment_value_and_strips_whitespace() -> None:
    value = load_secret("ADMIN_TOKEN", "default-token", {"ADMIN_TOKEN": "  configured-token  "})

    assert value == "configured-token"


def test_load_secret_uses_default_for_missing_or_blank_value() -> None:
    assert load_secret("ADMIN_TOKEN", "default-token", {}) == "default-token"
    assert load_secret("ADMIN_TOKEN", "default-token", {"ADMIN_TOKEN": "  "}) == "default-token"


def test_validate_required_secrets_rejects_blank_values() -> None:
    with pytest.raises(SystemExit, match="不能为空"):
        validate_required_secrets("", "proxy-secret-123456", set())


def test_validate_required_secrets_rejects_weak_or_short_values() -> None:
    weak = {"example-admin", "example-proxy"}

    with pytest.raises(SystemExit, match="ADMIN_TOKEN 使用了示例/弱密钥"):
        validate_required_secrets("example-admin", "proxy-secret-123456", weak)
    with pytest.raises(SystemExit, match="PROXY_SECRET 使用了示例/弱密钥"):
        validate_required_secrets("admin-secret-123456", "short", weak)


def test_validate_required_secrets_rejects_equal_values() -> None:
    with pytest.raises(SystemExit, match="不能相同"):
        validate_required_secrets("same-secret-123456", "same-secret-123456", set())


def test_validate_required_secrets_accepts_distinct_strong_values() -> None:
    validate_required_secrets("admin-secret-123456", "proxy-secret-123456", set())


def test_validate_environment_secrets_uses_the_canonical_defaults_and_rules() -> None:
    with pytest.raises(SystemExit, match="ADMIN_TOKEN 使用了示例/弱密钥"):
        validate_environment_secrets(
            {
                "ADMIN_TOKEN": DEFAULT_ADMIN_TOKEN,
                "PROXY_SECRET": "proxy-secret-123456",
            }
        )

    validate_environment_secrets(
        {
            "ADMIN_TOKEN": "admin-secret-123456",
            "PROXY_SECRET": "proxy-secret-123456",
        }
    )

    with pytest.raises(SystemExit, match="PROXY_SECRET 使用了示例/弱密钥"):
        validate_environment_secrets(
            {
                "ADMIN_TOKEN": "admin-secret-123456",
                "PROXY_SECRET": DEFAULT_PROXY_SECRET,
            }
        )
