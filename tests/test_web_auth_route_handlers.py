from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from docxtool.web.auth_route_handlers import (
    handle_auth_login,
    handle_auth_logout,
    handle_auth_me,
    handle_auth_register,
    read_auth_json_request,
)


class FakeHandler:
    """测试用 handler，保存认证路由所需请求字段和响应调用。"""

    def __init__(self, payload: dict | None = None) -> None:
        self.headers = {"Content-Type": "application/json", "User-Agent": "ua"}
        self.client_address = ("127.0.0.1", 12345)
        self.payload = payload or {}
        self.responses: list[tuple[str, object]] = []

    def _parsed_url(self):
        """无需传入数据，返回测试 URL 对象。"""
        return SimpleNamespace(path="/auth/login")

    def _request_params(self, _parsed) -> dict:
        """传入已解析 URL，返回测试请求参数。"""
        return self.payload

    def _json(self, obj: dict, status: int = 200, extra_headers=None) -> None:
        """传入 JSON 对象、状态码和可选头，记录 JSON 响应。"""
        self.responses.append(("json", (obj, status, extra_headers)))

    def _json_error_fields(self, error: tuple) -> None:
        """传入错误字段元组，记录 JSON 错误字段响应。"""
        self.responses.append(("json_error_fields", error))


class FakeConnection:
    """测试用数据库连接，按预设行返回查询结果并记录写入。"""

    def __init__(self, row=None, fail: Exception | None = None) -> None:
        self.row = row
        self.fail = fail
        self.executed: list[tuple[str, tuple]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, sql: str, args: tuple = ()):
        """传入 SQL 和参数，记录执行；配置异常时抛出，否则返回自身。"""
        if self.fail is not None:
            raise self.fail
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        """无需传入数据，返回预设数据库行。"""
        return self.row

    def commit(self) -> None:
        """无需传入数据，记录提交。"""
        self.committed = True

    def rollback(self) -> None:
        """无需传入数据，记录回滚。"""
        self.rolled_back = True

    def close(self) -> None:
        """无需传入数据，记录关闭。"""
        self.closed = True


class FakeRow(dict):
    """测试用用户行，支持字典键访问。"""


def test_read_auth_json_request_returns_payload_or_error() -> None:
    """认证 JSON 请求读取器应校验来源和 Content-Type，并返回 dict payload。"""
    ok = FakeHandler({"username": "alice"})
    bad = FakeHandler({})

    payload = read_auth_json_request(
        ok,
        origin_allowed=lambda _headers: True,
        json_request_error=lambda _origin, _headers: None,
    )
    failed = read_auth_json_request(
        bad,
        origin_allowed=lambda _headers: False,
        json_request_error=lambda _origin, _headers: ("ORIGIN_INVALID", "bad", 403),
    )

    assert payload == {"username": "alice"}
    assert failed is None
    assert bad.responses == [("json_error_fields", ("ORIGIN_INVALID", "bad", 403))]


def test_handle_auth_me_returns_principal_data_and_headers() -> None:
    """auth/me 处理器应从 principal 构造 data 和附加 Cookie 头。"""
    handler = FakeHandler()

    handle_auth_me(
        handler,
        principal=lambda _headers, _addr: {"authenticated": True, "cookie": "owner=1"},
        me_data=lambda principal: {"authenticated": principal["authenticated"]},
        me_extra_headers=lambda principal, clear_user_cookie_header: [("Set-Cookie", principal["cookie"]), ("Set-Cookie", clear_user_cookie_header)],
        ok_data_response=lambda data: {"ok": True, "data": data},
        user_cookie_header=lambda _token, clear=False: "user=clear" if clear else "user=1",
    )

    assert handler.responses == [
        (
            "json",
            (
                {"ok": True, "data": {"authenticated": True}},
                200,
                [("Set-Cookie", "owner=1"), ("Set-Cookie", "user=clear")],
            ),
        )
    ]


def test_handle_auth_register_creates_user_session_and_migrates_owner() -> None:
    """注册处理器应校验 payload、写入用户、迁移匿名 owner 并返回登录响应。"""
    handler = FakeHandler({"username": "Alice", "password": "pass"})
    conn = FakeConnection()
    migrated: list[tuple[str, str]] = []

    handle_auth_register(
        handler,
        read_json_request=lambda: handler.payload,
        auth_rate_allow=lambda *_args: (True, 0),
        client_ip=lambda *_args: "127.0.0.1",
        register_rate_limit_error=lambda allowed, retry: None if allowed else ("RATE_LIMITED", "slow", 429, retry),
        validate_username=lambda value: (value, value.lower()),
        validate_password=lambda value: value,
        validation_error_from_exception=lambda exc: ("VALIDATION_ERROR", str(exc), 400),
        principal=lambda *_args: {"owner_id": "anon-1"},
        new_user_id=lambda: "usr_1",
        now_unix=lambda: 123,
        sql_lock=nullcontext(),
        connect=lambda: conn,
        hash_password=lambda password: f"hash:{password}",
        migrate_anonymous_owner=lambda _conn, anon, user: migrated.append((anon, user)),
        register_error_from_exception=lambda exc: ("REGISTER_FAILED", str(exc), 500),
        create_user_session=lambda user_id, _ua, _ip: {"token": f"token:{user_id}", "csrf_token": "csrf"},
        success_response=lambda user_id, username, display, csrf: {"user_id": user_id, "username": username, "display": display, "csrf": csrf},
        session_extra_headers=lambda user_cookie, anon_cookie: [("Set-Cookie", user_cookie), ("Set-Cookie", anon_cookie)],
        user_cookie_header=lambda token: f"user={token}",
        anonymous_clear_cookie_header=lambda: "anon=clear",
    )

    assert migrated == [("anon-1", "usr_1")]
    assert conn.committed is True
    assert handler.responses == [
        (
            "json",
            (
                {"user_id": "usr_1", "username": "Alice", "display": "Alice", "csrf": "csrf"},
                201,
                [("Set-Cookie", "user=token:usr_1"), ("Set-Cookie", "anon=clear")],
            ),
        )
    ]


def test_handle_auth_register_reports_rate_and_validation_errors() -> None:
    """注册处理器应在限流或字段校验失败时返回稳定错误。"""
    limited = FakeHandler({"username": "Alice", "password": "pass"})
    invalid = FakeHandler({"username": "", "password": "pass"})

    common = {
        "read_json_request": lambda: {"username": "", "password": "pass"},
        "client_ip": lambda *_args: "127.0.0.1",
        "validate_password": lambda value: value,
        "principal": lambda *_args: {},
        "new_user_id": lambda: "usr_1",
        "now_unix": lambda: 123,
        "sql_lock": nullcontext(),
        "connect": lambda: FakeConnection(),
        "hash_password": lambda password: password,
        "migrate_anonymous_owner": lambda *_args: None,
        "register_error_from_exception": lambda exc: ("REGISTER_FAILED", str(exc), 500),
        "create_user_session": lambda *_args: {},
        "success_response": lambda *_args: {},
        "session_extra_headers": lambda *_args: [],
        "user_cookie_header": lambda _token: "",
        "anonymous_clear_cookie_header": lambda: "",
    }
    handle_auth_register(
        limited,
        auth_rate_allow=lambda *_args: (False, 9),
        register_rate_limit_error=lambda allowed, retry: None if allowed else ("RATE_LIMITED", "slow", 429, retry),
        validate_username=lambda value: (value, value),
        validation_error_from_exception=lambda exc: ("VALIDATION_ERROR", str(exc), 400),
        **common,
    )
    handle_auth_register(
        invalid,
        auth_rate_allow=lambda *_args: (True, 0),
        register_rate_limit_error=lambda allowed, retry: None if allowed else ("RATE_LIMITED", "slow", 429, retry),
        validate_username=lambda _value: (_ for _ in ()).throw(ValueError("USERNAME_REQUIRED: 用户名不能为空")),
        validation_error_from_exception=lambda exc: ("USERNAME_REQUIRED", "用户名不能为空", 400),
        **common,
    )

    assert limited.responses == [("json_error_fields", ("RATE_LIMITED", "slow", 429, 9))]
    assert invalid.responses == [("json_error_fields", ("USERNAME_REQUIRED", "用户名不能为空", 400))]


def test_handle_auth_login_updates_last_login_and_returns_session() -> None:
    """登录处理器应校验密码、更新登录时间、迁移匿名资源并返回 session。"""
    handler = FakeHandler({"username": "Alice", "password": "pass", "remember_me": "false"})
    row = FakeRow(id="usr_1", username="Alice", display_name="Alice A", username_norm="alice", password_hash="hash", status="active")
    query_conn = FakeConnection(row)
    update_conn = FakeConnection()
    conns = iter([query_conn, update_conn])
    migrated: list[tuple[str, str]] = []

    handle_auth_login(
        handler,
        read_json_request=lambda: handler.payload,
        validate_username=lambda value: (value, value.lower()),
        invalid_credentials_error=lambda: ("INVALID_CREDENTIALS", "bad", 401),
        client_ip=lambda *_args: "127.0.0.1",
        auth_rate_allow=lambda *_args: (True, 0),
        login_rate_limit_error=lambda *args: None,
        sql_lock=nullcontext(),
        connect=lambda: next(conns),
        verify_password=lambda _hash, password: (password == "pass", False),
        account_disabled_error=lambda: ("ACCOUNT_DISABLED", "disabled", 403),
        hash_password=lambda password: f"hash:{password}",
        now_unix=lambda: 123,
        principal=lambda *_args: {"owner_id": "anon-1"},
        migrate_anonymous_resources=lambda anon, user: migrated.append((anon, user)),
        create_user_session=lambda user_id, _ua, _ip: {"token": f"token:{user_id}", "csrf_token": "csrf"},
        parse_bool=lambda value, default: False if value == "false" else default,
        success_response=lambda user_id, username, display, csrf: {"user_id": user_id, "username": username, "display": display, "csrf": csrf},
        session_extra_headers=lambda user_cookie, anon_cookie: [("Set-Cookie", user_cookie), ("Set-Cookie", anon_cookie)],
        user_cookie_header=lambda token, persistent=True: f"user={token}; persistent={persistent}",
        anonymous_clear_cookie_header=lambda: "anon=clear",
    )

    assert migrated == [("anon-1", "usr_1")]
    assert update_conn.committed is True
    assert handler.responses == [
        (
            "json",
            (
                {"user_id": "usr_1", "username": "Alice", "display": "Alice A", "csrf": "csrf"},
                200,
                [("Set-Cookie", "user=token:usr_1; persistent=False"), ("Set-Cookie", "anon=clear")],
            ),
        )
    ]


def test_handle_auth_login_rejects_invalid_credentials_or_disabled_account() -> None:
    """登录处理器应拒绝无效凭据和停用账号。"""
    missing = FakeHandler({"username": "Alice", "password": "bad"})
    disabled = FakeHandler({"username": "Alice", "password": "pass"})

    common = {
        "read_json_request": lambda: {"username": "Alice", "password": "pass"},
        "validate_username": lambda value: (value, value.lower()),
        "invalid_credentials_error": lambda: ("INVALID_CREDENTIALS", "bad", 401),
        "client_ip": lambda *_args: "127.0.0.1",
        "auth_rate_allow": lambda *_args: (True, 0),
        "login_rate_limit_error": lambda *args: None,
        "sql_lock": nullcontext(),
        "verify_password": lambda _hash, password: (password == "pass", False),
        "account_disabled_error": lambda: ("ACCOUNT_DISABLED", "disabled", 403),
        "hash_password": lambda password: password,
        "now_unix": lambda: 123,
        "principal": lambda *_args: {},
        "migrate_anonymous_resources": lambda *_args: None,
        "create_user_session": lambda *_args: {},
        "parse_bool": lambda _value, default: default,
        "success_response": lambda *_args: {},
        "session_extra_headers": lambda *_args: [],
        "user_cookie_header": lambda *_args, **_kwargs: "",
        "anonymous_clear_cookie_header": lambda: "",
    }
    handle_auth_login(missing, connect=lambda: FakeConnection(None), **common)
    handle_auth_login(
        disabled,
        connect=lambda: FakeConnection(FakeRow(id="usr_1", username="Alice", display_name="Alice", password_hash="hash", status="disabled")),
        **common,
    )

    assert missing.responses == [("json_error_fields", ("INVALID_CREDENTIALS", "bad", 401))]
    assert disabled.responses == [("json_error_fields", ("ACCOUNT_DISABLED", "disabled", 403))]


def test_handle_auth_logout_checks_origin_csrf_and_clears_cookie() -> None:
    """退出处理器应校验来源和 CSRF，通过后删除 session 并清除 Cookie。"""
    handler = FakeHandler()
    deleted: list[dict] = []

    handle_auth_logout(
        handler,
        origin_allowed=lambda _headers: True,
        logout_request_error=lambda origin, authenticated, csrf: None if origin and (not authenticated or csrf) else ("CSRF_INVALID", "bad", 403),
        principal=lambda *_args: {"authenticated": True, "csrf_token": "csrf"},
        auth_csrf_allowed=lambda _headers, _principal: True,
        delete_user_session=lambda headers: deleted.append(headers),
        logout_response=lambda: {"ok": True, "data": {"logged_out": True}},
        logout_extra_headers=lambda clear_cookie: [("Set-Cookie", clear_cookie)],
        user_cookie_header=lambda token, clear=False: "user=clear" if clear else f"user={token}",
    )

    assert deleted == [handler.headers]
    assert handler.responses == [
        ("json", ({"ok": True, "data": {"logged_out": True}}, 200, [("Set-Cookie", "user=clear")]))
    ]
