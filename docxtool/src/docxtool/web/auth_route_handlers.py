"""User authentication route handlers for the Web compatibility app."""

from __future__ import annotations

from typing import Any


def read_auth_json_request(handler: Any, *, origin_allowed, json_request_error) -> dict | None:
    """传入 handler、来源校验和 JSON 校验回调，返回认证请求参数或发送错误后返回 None。"""
    error = json_request_error(origin_allowed(handler.headers), handler.headers)
    if error is not None:
        handler._json_error_fields(error)
        return None
    payload = handler._request_params(handler._parsed_url())
    return payload if isinstance(payload, dict) else None


def handle_auth_me(
    handler: Any,
    *,
    principal,
    me_data,
    me_extra_headers,
    ok_data_response,
    user_cookie_header,
) -> None:
    """传入 handler 和 principal/响应构造回调，发送 /auth/me JSON 响应。"""
    principal_data = principal(handler.headers, handler.client_address)
    data = me_data(principal_data)
    extra = me_extra_headers(principal_data, clear_user_cookie_header=user_cookie_header("", clear=True))
    handler._json(ok_data_response(data), extra_headers=extra)


def handle_auth_register(
    handler: Any,
    *,
    read_json_request,
    auth_rate_allow,
    client_ip,
    register_rate_limit_error,
    validate_username,
    validate_password,
    validation_error_from_exception,
    principal,
    new_user_id,
    now_unix,
    sql_lock,
    connect,
    hash_password,
    migrate_anonymous_owner,
    register_error_from_exception,
    create_user_session,
    success_response,
    session_extra_headers,
    user_cookie_header,
    anonymous_clear_cookie_header,
) -> None:
    """传入 handler、校验/数据库/session 回调，注册用户并发送成功或错误响应。"""
    payload = read_json_request()
    if payload is None:
        return
    allowed, retry = auth_rate_allow("register-ip", client_ip(handler.headers, handler.client_address), 3600, 5)
    rate_error = register_rate_limit_error(allowed, retry)
    if rate_error is not None:
        handler._json_error_fields(rate_error)
        return
    try:
        display, username_norm = validate_username(payload.get("username", ""))
        password = validate_password(payload.get("password", ""))
    except ValueError as exc:
        handler._json_error_fields(validation_error_from_exception(exc))
        return
    anonymous = principal(handler.headers, handler.client_address)
    user_id = new_user_id()
    now = now_unix()
    conn = None
    try:
        with sql_lock:
            conn = connect()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO users(id,username,username_norm,password_hash,display_name,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (user_id, display, username_norm, hash_password(password), display, now, now),
            )
            migrate_anonymous_owner(conn, anonymous.get("owner_id", ""), user_id)
            conn.commit()
            conn.close()
    except Exception as exc:
        if conn is not None:
            conn.rollback()
            conn.close()
        handler._json_error_fields(register_error_from_exception(exc))
        return
    session = create_user_session(
        user_id,
        handler.headers.get("User-Agent", ""),
        handler.client_address[0] if handler.client_address else "",
    )
    handler._json(
        success_response(user_id, display, display, session["csrf_token"]),
        201,
        session_extra_headers(
            user_cookie_header(session["token"]),
            anonymous_clear_cookie_header(),
        ),
    )


def handle_auth_login(
    handler: Any,
    *,
    read_json_request,
    validate_username,
    invalid_credentials_error,
    client_ip,
    auth_rate_allow,
    login_rate_limit_error,
    sql_lock,
    connect,
    verify_password,
    account_disabled_error,
    hash_password,
    now_unix,
    principal,
    migrate_anonymous_resources,
    create_user_session,
    parse_bool,
    success_response,
    session_extra_headers,
    user_cookie_header,
    anonymous_clear_cookie_header,
) -> None:
    """传入 handler、校验/数据库/session 回调，登录用户并发送成功或错误响应。"""
    payload = read_json_request()
    if payload is None:
        return
    try:
        _, username_norm = validate_username(payload.get("username", ""))
    except ValueError:
        handler._json_error_fields(invalid_credentials_error())
        return
    ip = client_ip(handler.headers, handler.client_address)
    ip_allowed, ip_retry = auth_rate_allow("login-ip", ip, 600, 30)
    name_allowed, name_retry = auth_rate_allow("login-name", username_norm, 600, 10)
    rate_error = login_rate_limit_error(ip_allowed, ip_retry, name_allowed, name_retry)
    if rate_error is not None:
        handler._json_error_fields(rate_error)
        return
    password = str(payload.get("password", ""))
    with sql_lock:
        conn = connect()
        row = conn.execute("SELECT * FROM users WHERE username_norm=?", (username_norm,)).fetchone()
        conn.close()
    if not row or not verify_password(row["password_hash"], password)[0]:
        handler._json_error_fields(invalid_credentials_error())
        return
    if row["status"] != "active":
        handler._json_error_fields(account_disabled_error())
        return
    _, needs_rehash = verify_password(row["password_hash"], password)
    with sql_lock:
        conn = connect()
        now = now_unix()
        if needs_rehash:
            conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?", (hash_password(password), now, row["id"]))
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now, row["id"]))
        conn.commit()
        conn.close()
    principal_data = principal(handler.headers, handler.client_address)
    migrate_anonymous_resources(principal_data.get("owner_id", ""), row["id"])
    session = create_user_session(
        row["id"],
        handler.headers.get("User-Agent", ""),
        handler.client_address[0] if handler.client_address else "",
    )
    remember_me = parse_bool(str(payload.get("remember_me", "true")), True)
    handler._json(
        success_response(row["id"], row["username"], row["display_name"], session["csrf_token"]),
        extra_headers=session_extra_headers(
            user_cookie_header(session["token"], persistent=remember_me),
            anonymous_clear_cookie_header(),
        ),
    )


def handle_auth_logout(
    handler: Any,
    *,
    origin_allowed,
    logout_request_error,
    principal,
    auth_csrf_allowed,
    delete_user_session,
    logout_response,
    logout_extra_headers,
    user_cookie_header,
) -> None:
    """传入 handler、来源/CSRF/session 回调，退出登录并发送 JSON 响应。"""
    origin_error = logout_request_error(origin_allowed(handler.headers), False, False)
    if origin_error is not None:
        handler._json_error_fields(origin_error)
        return
    principal_data = principal(handler.headers, handler.client_address)
    csrf_error = logout_request_error(
        True,
        bool(principal_data.get("authenticated")),
        auth_csrf_allowed(handler.headers, principal_data),
    )
    if csrf_error is not None:
        handler._json_error_fields(csrf_error)
        return
    delete_user_session(handler.headers)
    handler._json(
        logout_response(),
        extra_headers=logout_extra_headers(user_cookie_header("", True)),
    )
