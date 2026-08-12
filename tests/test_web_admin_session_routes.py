from __future__ import annotations

import io

from docxtool.web.admin_session_routes import handle_admin_login, handle_admin_logout, handle_admin_session


class FakeHandler:
    """测试用 handler，保存管理员 session 路由处理需要的请求和响应。"""

    def __init__(self, body: bytes = b"") -> None:
        self.headers = {"Cookie": "admin=1", "Content-Length": str(len(body)), "User-Agent": "ua"}
        self.client_address = ("127.0.0.1", 12345)
        self.rfile = io.BytesIO(body)
        self.responses: list[tuple[str, object]] = []

    def _json(self, obj: dict) -> None:
        """传入 JSON 对象，记录 JSON 响应。"""
        self.responses.append(("json", obj))

    def _json_error(self, code: str, message: str, status: int) -> None:
        """传入错误码、提示和状态码，记录 JSON 错误响应。"""
        self.responses.append(("json_error", (code, message, status)))

    def _json_error_fields(self, error: tuple[str, str, int]) -> None:
        """传入错误字段元组，记录 JSON 错误字段响应。"""
        self.responses.append(("json_error_fields", error))

    def _redirect(self, target: str, extra_headers=None) -> None:
        """传入目标地址和可选响应头，记录跳转响应。"""
        self.responses.append(("redirect", (target, extra_headers)))


def test_handle_admin_session_returns_payload_or_unauthorized() -> None:
    """管理员 session 处理器应返回 session payload 或未授权错误。"""
    ok = FakeHandler()
    missing = FakeHandler()

    handle_admin_session(
        ok,
        session_from_headers=lambda _headers, _cookie: {"session_id": "sid", "csrf_token": "csrf"},
        session_payload=lambda session: {"ok": True, "csrf": session["csrf_token"]},
    )
    handle_admin_session(
        missing,
        session_from_headers=lambda _headers, _cookie: {},
        session_payload=lambda session: session,
    )

    assert ok.responses == [("json", {"ok": True, "csrf": "csrf"})]
    assert missing.responses == [("json_error", ("UNAUTHORIZED", "需要管理员权限", 403))]


def test_handle_admin_login_rejects_invalid_token() -> None:
    """管理员登录处理器应在密钥错误时返回稳定错误字段。"""
    handler = FakeHandler(b"token=bad")

    handle_admin_login(
        handler,
        admin_token="secret",
        read_exact=lambda stream, length: stream.read(length),
        parse_login_token=lambda body: body.decode("utf-8").split("=", 1)[1],
        login_error=lambda token, expected: None if token == expected else ("INVALID_LOGIN", "管理员密钥错误", 403),
        create_admin_session=lambda *_args: {"session_id": "sid"},
        admin_cookie_header=lambda session_id: f"admin={session_id}",
    )

    assert handler.responses == [("json_error_fields", ("INVALID_LOGIN", "管理员密钥错误", 403))]


def test_handle_admin_login_creates_session_and_redirects() -> None:
    """管理员登录处理器应读取表单、创建 session、写入 Cookie 并跳转监控页。"""
    calls: list[tuple[str, object]] = []
    handler = FakeHandler(b"token=secret")

    handle_admin_login(
        handler,
        admin_token="secret",
        read_exact=lambda stream, length: stream.read(length),
        parse_login_token=lambda body: body.decode("utf-8").split("=", 1)[1],
        login_error=lambda token, expected: None if token == expected else ("INVALID_LOGIN", "bad", 403),
        create_admin_session=lambda ua, ip: calls.append(("create", (ua, ip))) or {"session_id": "sid"},
        admin_cookie_header=lambda session_id: f"admin={session_id}",
    )

    assert calls == [("create", ("ua", "127.0.0.1"))]
    assert handler.responses == [("redirect", ("/admin", [("Set-Cookie", "admin=sid")]))]


def test_handle_admin_logout_deletes_session_and_clears_cookie() -> None:
    """管理员退出处理器应删除已有 session、清理 Cookie 并跳转登录页。"""
    deleted: list[str] = []
    handler = FakeHandler()

    handle_admin_logout(
        handler,
        session_from_headers=lambda _headers, _cookie: {"session_id": "sid"},
        delete_admin_session=deleted.append,
        logout_cookie_header=lambda cookie_name, secure=False: f"{cookie_name}=; secure={secure}",
        cookie_name="admin_session",
        secure=True,
    )

    assert deleted == ["sid"]
    assert handler.responses == [("redirect", ("/admin/login", [("Set-Cookie", "admin_session=; secure=True")]))]
