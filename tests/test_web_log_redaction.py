from __future__ import annotations

from docxtool.web.log_redaction import redact_sensitive_log


def test_redact_sensitive_log_hides_config_tokens_headers_and_cookies() -> None:
    source = "\n".join(
        [
            "ADMIN_TOKEN=private-admin-token",
            "PROXY_SECRET: private-proxy-secret",
            "Authorization: Bearer user-token",
            "Proxy-Authorization: Bearer proxy-token",
            "Cookie: docxtool_admin_session=session-id",
            "Set-Cookie: docxtool_user_session=user-session",
            "normal line remains visible",
        ]
    )

    redacted = redact_sensitive_log(source)

    assert "private-admin-token" not in redacted
    assert "private-proxy-secret" not in redacted
    assert "Bearer user-token" not in redacted
    assert "Bearer proxy-token" not in redacted
    assert "session-id" not in redacted
    assert "user-session" not in redacted
    assert "ADMIN_TOKEN=[REDACTED]" in redacted
    assert "PROXY_SECRET: [REDACTED]" in redacted
    assert "normal line remains visible" in redacted


def test_redact_sensitive_log_is_case_insensitive_and_line_anchored() -> None:
    source = "\n".join(
        [
            "authorization: Bearer lower-case",
            "message contains Cookie: visible inline text",
        ]
    )

    redacted = redact_sensitive_log(source)

    assert "Bearer lower-case" not in redacted
    assert "authorization: [REDACTED]" in redacted
    assert "message contains Cookie: visible inline text" in redacted


def test_redact_sensitive_log_accepts_none_and_custom_field_names() -> None:
    assert redact_sensitive_log(None) == ""

    redacted = redact_sensitive_log("X-Secret: value\nCookie: visible", field_names=("X-Secret",))

    assert redacted == "X-Secret: [REDACTED]\nCookie: visible"
