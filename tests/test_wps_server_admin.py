import hashlib
import logging
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from docxtool.wps_server import database
from docxtool.wps_server.admin import (
    WpsAdminError,
    delete_user,
    list_admin_audit_logs,
    list_devices,
    list_format_requests,
    list_users,
    overview,
    overview_trend,
    reset_user_password,
    send_notification,
    set_device_status,
    set_user_status,
    user_detail,
)
from docxtool.wps_server.auth import WpsAuthError, authenticated_session
from docxtool.wps_server.service import (
    WpsServiceError,
    acknowledge_notifications,
    list_pending_notifications,
    login_user,
    register_user,
)
from docxtool.wps_server.admin_routes import (
    handle_devices,
    handle_device_status,
    handle_overview,
    handle_tasks,
    handle_user,
    handle_user_delete,
    handle_user_notification,
    handle_user_password_reset,
    handle_user_status,
    handle_users,
)
from docxtool.web.admin_workspace_page import (
    render_wps_devices_page,
    render_wps_overview_page,
    render_wps_tasks_page,
    render_wps_user_page,
    render_wps_users_page,
)


def _seed(tmp_path):
    path = tmp_path / "wps_plugin.db"

    def connect():
        return database.connect(path)

    lock = threading.Lock()
    database.initialize_database(connect, lock)
    registered = register_user(
        {
            "username": "User01",
            "password": "Pass01",
            "device": {
                "device_key": "device-key-001",
                "device_name": "测试电脑",
                "platform": "windows",
                "app_version": "5.1",
            },
        },
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1000,
        config_version="config-1",
    )
    return path, connect, lock, registered


def _actor():
    return {"actor_type": "session", "actor_session_id_short": "adminsession1234"}


def test_admin_summary_search_and_status_changes(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="docx_tool")
    path, connect, lock, registered = _seed(tmp_path)
    summary = overview(connect_func=connect, sql_lock=lock, now=1100)
    user_page = list_users(connect_func=connect, sql_lock=lock, now=1100, query="user01")

    assert summary == {
        "users": 1,
        "online_devices": 1,
        "requests": 0,
        "pending": 0,
        "success": 0,
        "failed": 0,
        "average_duration_ms": 0,
    }
    assert user_page["total"] == 1
    assert len(user_page["rows"]) == 1
    assert user_page["rows"][0]["device_count"] == 1

    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "ALTER TABLE wps_users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"
        )
        conn.execute("UPDATE wps_users SET display_name='Legacy Alias'")
        conn.commit()
    assert list_users(
        connect_func=connect,
        sql_lock=lock,
        now=1100,
        query="legacy alias",
    )["rows"] == []

    set_user_status(
        registered["user"]["id"],
        "disabled",
        connect_func=connect,
        sql_lock=lock,
        now=1200,
        actor=_actor(),
        correlation_id="adm_status_disable",
    )
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT status FROM wps_users").fetchone()[0] == "disabled"
        assert conn.execute("SELECT COUNT(*) FROM wps_sessions").fetchone()[0] == 0
    with pytest.raises(WpsAuthError, match="SESSION_INVALID"):
        authenticated_session(
            {"Authorization": f"Bearer {registered['session_token']}"},
            connect_func=connect,
            sql_lock=lock,
            now_func=lambda: 1201,
        )

    set_user_status(
        registered["user"]["id"],
        "active",
        connect_func=connect,
        sql_lock=lock,
        now=1300,
        actor=_actor(),
        correlation_id="adm_status_enable",
    )
    logged_in = login_user(
        {
            "username": "User01",
            "password": "Pass01",
            "device": {
                "device_key": "device-key-001",
                "device_name": "测试电脑",
                "platform": "windows",
                "app_version": "5.1",
            },
        },
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1301,
        config_version="config-1",
    )
    set_device_status(
        registered["device"]["id"],
        "disabled",
        connect_func=connect,
        sql_lock=lock,
        now=1302,
        actor=_actor(),
        correlation_id="adm_device_disable",
    )
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT status FROM wps_devices").fetchone()[0] == "disabled"
    with pytest.raises(WpsAuthError, match="SESSION_INVALID"):
        authenticated_session(
            {"Authorization": f"Bearer {logged_in['session_token']}"},
            connect_func=connect,
            sql_lock=lock,
            now_func=lambda: 1302,
        )
    with sqlite3.connect(str(path)) as conn:
        audit_rows = conn.execute(
            "SELECT actor_type,actor_session_id_short,target_user_id,event,result,error_code "
            "FROM wps_admin_audit_logs ORDER BY created_at,audit_id"
        ).fetchall()
    assert [tuple(row) for row in audit_rows] == [
        ("session", "adminsession1234", registered["user"]["id"], "wps.admin.user.status.updated", "success", ""),
        ("session", "adminsession1234", registered["user"]["id"], "wps.admin.user.status.updated", "success", ""),
        ("session", "adminsession1234", registered["user"]["id"], "wps.admin.device.status.updated", "success", ""),
    ]
    assert "wps.admin.user.status.success" in caplog.text
    assert "wps.admin.device.status.success" in caplog.text


def test_failed_admin_mutation_does_not_write_a_success_audit_fact(tmp_path):
    path, connect, lock, _registered = _seed(tmp_path)

    with pytest.raises(WpsAdminError, match="WPS_USER_NOT_FOUND"):
        set_user_status(
            "wusr_missing",
            "disabled",
            connect_func=connect,
            sql_lock=lock,
            now=1200,
            actor=_actor(),
            correlation_id="adm_missing_user",
        )

    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_admin_audit_logs").fetchone()[0] == 0


def test_admin_status_posts_are_fail_closed_until_the_server_gate_is_enabled(tmp_path):
    path, connect, lock, registered = _seed(tmp_path)

    class Handler:
        def __init__(self):
            self.responses = []
            self._admin_context = {
                "authorized": True,
                "session": {"session_id": "real-admin-session-id"},
                "legacy_token": False,
            }

        def _json_error(self, code, message, status):
            self.responses.append(("error", code, message, status))

        def _redirect(self, target):
            self.responses.append(("redirect", target))

    def require_admin_post(_parsed):
        return True

    handler = Handler()
    handle_user_status(
        handler,
        SimpleNamespace(query=""),
        registered["user"]["id"],
        require_admin_post=require_admin_post,
        request_params=lambda _parsed: {"status": "disabled"},
        wps_connect=connect,
        wps_lock=lock,
        now_func=lambda: 1200,
        mutations_enabled=False,
    )
    assert handler.responses == [
        ("error", "WPS_ADMIN_MUTATIONS_DISABLED", "WPS 管理写操作尚未启用", 403)
    ]
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT status FROM wps_users").fetchone()[0] == "active"
        assert conn.execute("SELECT COUNT(*) FROM wps_admin_audit_logs").fetchone()[0] == 0

    enabled_handler = Handler()
    handle_user_status(
        enabled_handler,
        SimpleNamespace(query=""),
        registered["user"]["id"],
        require_admin_post=require_admin_post,
        request_params=lambda _parsed: {"status": "disabled"},
        wps_connect=connect,
        wps_lock=lock,
        now_func=lambda: 1201,
        mutations_enabled=True,
    )
    assert enabled_handler.responses == [
        ("redirect", f"/admin/wps/users/{registered['user']['id']}?tab=security")
    ]
    with sqlite3.connect(str(path)) as conn:
        actor_short = conn.execute(
            "SELECT actor_session_id_short FROM wps_admin_audit_logs"
        ).fetchone()[0]
    assert actor_short == hashlib.sha256(b"real-admin-session-id").hexdigest()[:16]


def test_admin_password_reset_delete_and_audit_lifecycle(tmp_path):
    path, connect, lock, registered = _seed(tmp_path)
    user_id = registered["user"]["id"]
    device_id = registered["device"]["id"]

    reset_user_password(
        user_id,
        "NewPass01",
        connect_func=connect,
        sql_lock=lock,
        now=1200,
        actor=_actor(),
        correlation_id="adm_reset_password",
    )
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_sessions WHERE user_id=?", (user_id,)).fetchone()[0] == 0
    with pytest.raises(WpsServiceError, match="INVALID_CREDENTIALS"):
        login_user(
            {
                "username": "User01",
                "password": "Pass01",
                "device": {
                    "device_key": "device-key-001",
                    "device_name": "测试电脑",
                    "platform": "windows",
                    "app_version": "5.1",
                },
            },
            connect_func=connect,
            sql_lock=lock,
            client_ip="127.0.0.1",
            now_func=lambda: 1201,
            config_version="config-1",
        )
    login_user(
        {
            "username": "User01",
            "password": "NewPass01",
            "device": {
                "device_key": "device-key-001",
                "device_name": "测试电脑",
                "platform": "windows",
                "app_version": "5.1",
            },
        },
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1202,
        config_version="config-1",
    )
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """INSERT INTO wps_format_requests
               (request_id,user_id,device_id,command,status,config_version,requested_at,app_version)
               VALUES ('request-delete',?,?, 'apply','authorized','config-1',1203,'5.1')""",
            (user_id, device_id),
        )
        conn.commit()

    with pytest.raises(WpsAdminError, match="WPS_ADMIN_DELETE_CONFIRMATION_INVALID"):
        delete_user(
            user_id,
            "WrongUser",
            connect_func=connect,
            sql_lock=lock,
            now=1204,
            actor=_actor(),
            correlation_id="adm_delete_denied",
        )
    assert user_detail(user_id, connect_func=connect, sql_lock=lock, now=1205)["user"]["id"] == user_id

    delete_user(
        user_id,
        "User01",
        connect_func=connect,
        sql_lock=lock,
        now=1206,
        actor=_actor(),
        correlation_id="adm_delete_success",
    )
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_users").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM wps_devices").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM wps_sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM wps_format_requests").fetchone()[0] == 0
    audit = list_admin_audit_logs(
        user_id,
        connect_func=connect,
        sql_lock=lock,
        page_size=20,
    )
    assert [(row["event"], row["result"], row["error_code"]) for row in audit["rows"]] == [
        ("wps.admin.user.deleted", "success", ""),
        ("wps.admin.user.delete.denied", "denied", "WPS_ADMIN_DELETE_CONFIRMATION_INVALID"),
        ("wps.admin.user.password_reset", "success", ""),
    ]


def test_admin_mutation_rolls_back_when_persistent_audit_write_fails(tmp_path):
    path, connect, lock, registered = _seed(tmp_path)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """CREATE TRIGGER reject_wps_audit
               BEFORE INSERT ON wps_admin_audit_logs
               BEGIN SELECT RAISE(ABORT, 'audit rejected'); END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="audit rejected"):
        set_device_status(
            registered["device"]["id"],
            "disabled",
            connect_func=connect,
            sql_lock=lock,
            now=1300,
            actor=_actor(),
            correlation_id="adm_audit_rollback",
        )

    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT status FROM wps_devices").fetchone()[0] == "active"
        assert conn.execute("SELECT COUNT(*) FROM wps_sessions").fetchone()[0] == 1


def test_account_notification_is_audited_acknowledged_idempotently_and_deleted(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="docx_tool")
    path, connect, lock, registered = _seed(tmp_path)
    user_id = registered["user"]["id"]
    notification_id = send_notification(
        user_id,
        "维护通知",
        "<b>仅作为纯文本显示</b>",
        "warning",
        connect_func=connect,
        sql_lock=lock,
        now=1200,
        actor=_actor(),
        correlation_id="adm_notification_send",
    )
    pending = list_pending_notifications(user_id, connect_func=connect, sql_lock=lock)
    assert pending == [
        {
            "notification_id": notification_id,
            "title": "维护通知",
            "body": "<b>仅作为纯文本显示</b>",
            "level": "warning",
            "created_at": 1200,
        }
    ]
    principal = authenticated_session(
        {"Authorization": f"Bearer {registered['session_token']}"},
        connect_func=connect,
        sql_lock=lock,
        now_func=lambda: 1201,
    )
    first = acknowledge_notifications(
        principal,
        {"notification_ids": [notification_id, "wnot_00000000000000000000000000000000"]},
        connect_func=connect,
        sql_lock=lock,
        now_func=lambda: 1202,
    )
    assert first == {"acknowledged_notification_ids": [notification_id]}
    second = acknowledge_notifications(
        principal,
        {"notification_ids": [notification_id]},
        connect_func=connect,
        sql_lock=lock,
        now_func=lambda: 1203,
    )
    assert second == {"acknowledged_notification_ids": []}
    assert list_pending_notifications(user_id, connect_func=connect, sql_lock=lock) == []

    remaining = send_notification(
        user_id,
        "待删除通知",
        "该通知随账号删除。",
        "info",
        connect_func=connect,
        sql_lock=lock,
        now=1204,
        actor=_actor(),
        correlation_id="adm_notification_delete",
    )
    assert remaining.startswith("wnot_")
    delete_user(
        user_id,
        "User01",
        connect_func=connect,
        sql_lock=lock,
        now=1205,
        actor=_actor(),
        correlation_id="adm_notification_user_delete",
    )
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_notifications").fetchone()[0] == 0
        audit_events = [
            row[0]
            for row in conn.execute(
                "SELECT event FROM wps_admin_audit_logs ORDER BY created_at, audit_id"
            ).fetchall()
        ]
    assert audit_events == [
        "wps.admin.notification.sent",
        "wps.admin.notification.sent",
        "wps.admin.user.deleted",
    ]
    assert "wps.admin.notification.send.success" in caplog.text
    assert "<b>仅作为纯文本显示</b>" not in caplog.text


def test_notification_send_route_is_gated_and_uses_canonical_redirect(tmp_path):
    path, connect, lock, registered = _seed(tmp_path)

    class Handler:
        def __init__(self):
            self.responses = []
            self._admin_context = {
                "authorized": True,
                "session": {"session_id": "real-admin-session-id"},
                "legacy_token": False,
            }

        def _json_error(self, code, message, status):
            self.responses.append(("error", code, message, status))

        def _redirect(self, target):
            self.responses.append(("redirect", target))

    common = {
        "require_admin_post": lambda _parsed: True,
        "request_params": lambda _parsed: {
            "title": "通知标题",
            "body": "通知正文",
            "level": "info",
        },
        "wps_connect": connect,
        "wps_lock": lock,
        "now_func": lambda: 1300,
    }
    disabled = Handler()
    handle_user_notification(
        disabled,
        SimpleNamespace(query=""),
        registered["user"]["id"],
        mutations_enabled=False,
        **common,
    )
    assert disabled.responses[0][1] == "WPS_ADMIN_MUTATIONS_DISABLED"

    enabled = Handler()
    handle_user_notification(
        enabled,
        SimpleNamespace(query=""),
        registered["user"]["id"],
        mutations_enabled=True,
        **common,
    )
    assert enabled.responses == [
        ("redirect", f"/admin/wps/users/{registered['user']['id']}?tab=security")
    ]
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_notifications").fetchone()[0] == 1
        assert conn.execute(
            "SELECT event FROM wps_admin_audit_logs"
        ).fetchone()[0] == "wps.admin.notification.sent"


def test_password_reset_and_delete_routes_are_gated_and_use_canonical_redirects(tmp_path):
    path, connect, lock, registered = _seed(tmp_path)

    class Handler:
        def __init__(self):
            self.responses = []
            self._admin_context = {
                "authorized": True,
                "session": {"session_id": "real-admin-session-id"},
                "legacy_token": False,
            }

        def _json_error(self, code, message, status):
            self.responses.append(("error", code, message, status))

        def _redirect(self, target):
            self.responses.append(("redirect", target))

    common = {
        "require_admin_post": lambda _parsed: True,
        "wps_connect": connect,
        "wps_lock": lock,
        "now_func": lambda: 1400,
    }
    user_id = registered["user"]["id"]
    disabled = Handler()
    handle_user_password_reset(
        disabled,
        SimpleNamespace(query=""),
        user_id,
        request_params=lambda _parsed: {"password": "NewPass01", "password_confirmation": "NewPass01"},
        mutations_enabled=False,
        **common,
    )
    assert disabled.responses[0][1] == "WPS_ADMIN_MUTATIONS_DISABLED"

    mismatch = Handler()
    handle_user_password_reset(
        mismatch,
        SimpleNamespace(query=""),
        user_id,
        request_params=lambda _parsed: {"password": "NewPass01", "password_confirmation": "OtherPass01"},
        mutations_enabled=True,
        **common,
    )
    assert mismatch.responses == [("error", "WPS_ADMIN_PASSWORD_CONFIRMATION_INVALID", "两次输入的密码不一致", 400)]

    reset = Handler()
    handle_user_password_reset(
        reset,
        SimpleNamespace(query=""),
        user_id,
        request_params=lambda _parsed: {"password": "NewPass01", "password_confirmation": "NewPass01"},
        mutations_enabled=True,
        **common,
    )
    assert reset.responses == [("redirect", f"/admin/wps/users/{user_id}?tab=security")]

    deleted = Handler()
    handle_user_delete(
        deleted,
        SimpleNamespace(query=""),
        user_id,
        request_params=lambda _parsed: {"confirmation_username": "User01"},
        mutations_enabled=True,
        **common,
    )
    assert deleted.responses == [("redirect", "/admin/wps/users")]
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_users").fetchone()[0] == 0


def test_device_status_route_uses_the_database_owner_for_its_redirect(tmp_path):
    path, connect, lock, registered = _seed(tmp_path)

    class Handler:
        def __init__(self):
            self.responses = []
            self._admin_context = {
                "authorized": True,
                "session": {"session_id": "real-admin-session-id"},
                "legacy_token": False,
            }

        def _json_error(self, code, message, status):
            self.responses.append(("error", code, message, status))

        def _redirect(self, target):
            self.responses.append(("redirect", target))

    handler = Handler()
    handle_device_status(
        handler,
        SimpleNamespace(query=""),
        registered["device"]["id"],
        require_admin_post=lambda _parsed: True,
        request_params=lambda _parsed: {"status": "disabled", "user_id": "untrusted-user-id"},
        wps_connect=connect,
        wps_lock=lock,
        now_func=lambda: 1500,
        mutations_enabled=True,
    )

    assert handler.responses == [
        ("redirect", f"/admin/wps/users/{registered['user']['id']}?tab=devices")
    ]
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT status FROM wps_devices").fetchone()[0] == "disabled"


def test_admin_queries_use_real_server_pagination_and_user_scoping(tmp_path):
    """用户、设备和请求页应使用总数加 LIMIT/OFFSET，而非固定 200 条。"""
    path, connect, lock, registered = _seed(tmp_path)
    second = register_user(
        {
            "username": "User02",
            "password": "Pass02",
            "device": {
                "device_key": "device-key-002",
                "device_name": "第二台电脑",
                "platform": "windows",
                "app_version": "5.2",
            },
        },
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.2",
        now_func=lambda: 2000,
        config_version="config-1",
    )
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """INSERT INTO wps_format_requests
               (request_id,user_id,device_id,command,status,config_version,requested_at,finished_at,duration_ms,error_code,app_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "request-001",
                registered["user"]["id"],
                registered["device"]["id"],
                "format",
                "success",
                "config-1",
                1500,
                1501,
                120,
                "",
                "5.1",
            ),
        )
        conn.execute(
            "UPDATE wps_devices SET last_seen_at=0 WHERE id=?",
            (second["device"]["id"],),
        )
        conn.commit()

    users = list_users(connect_func=connect, sql_lock=lock, now=2100, page=99, page_size=1)
    users_by_version = list_users(
        connect_func=connect,
        sql_lock=lock,
        now=2100,
        version="5.1",
        page_size=20,
    )
    users_online = list_users(
        connect_func=connect,
        sql_lock=lock,
        now=2100,
        online="online",
        page_size=20,
    )
    users_offline = list_users(
        connect_func=connect,
        sql_lock=lock,
        now=2100,
        online="offline",
        page_size=20,
    )
    devices = list_devices(connect_func=connect, sql_lock=lock, now=2100, version="5.1", page_size=20)
    requests = list_format_requests(connect_func=connect, sql_lock=lock, query="request-001", page_size=20)
    detail = user_detail(registered["user"]["id"], connect_func=connect, sql_lock=lock, now=2100)
    trend = overview_trend(connect_func=connect, sql_lock=lock, now=2100)

    assert users["total"] == 2
    assert users["page"] == 2
    assert len(users["rows"]) == 1
    assert users_by_version["total"] == 1
    assert users_by_version["rows"][0]["id"] == registered["user"]["id"]
    assert [row["id"] for row in users_online["rows"]] == [registered["user"]["id"]]
    assert [row["id"] for row in users_offline["rows"]] == [second["user"]["id"]]
    assert devices["total"] == 1
    assert devices["rows"][0]["user_id"] == registered["user"]["id"]
    assert requests["total"] == 1
    assert requests["rows"][0]["username"] == "User01"
    assert detail["summary"] == {
        "device_count": 1,
        "online_devices": 1,
        "format_total": 1,
        "format_success": 1,
        "format_failed": 0,
        "format_pending": 0,
        "average_duration_ms": 120.0,
    }
    assert detail["current_device"]["app_version"] == "5.1"
    assert detail["current_device"]["online"] == 1
    assert trend == [{"date": "1970-01-01", "total": 1, "success": 1, "failed": 0}]
    assert second["user"]["id"] != registered["user"]["id"]


def test_admin_route_handlers_render_all_phase_a_read_only_wps_pages(tmp_path):
    """新的 WPS 路由应把数据查询和页面渲染按职责衔接。"""
    _path, connect, lock, registered = _seed(tmp_path)

    class FakeHandler:
        def __init__(self):
            self.responses = []

        def _admin_csrf_token(self, _parsed):
            return "csrf"

        def _text(self, body, mime):
            self.responses.append((body, mime))

        def send_error(self, status):
            self.responses.append(("error", status))

    handlers = [
        (handle_overview, SimpleNamespace(query=""), render_wps_overview_page),
        (handle_users, SimpleNamespace(query="page_size=20"), render_wps_users_page),
        (handle_devices, SimpleNamespace(query="online=online"), render_wps_devices_page),
        (handle_tasks, SimpleNamespace(query=""), render_wps_tasks_page),
        (handle_user, SimpleNamespace(query="tab=devices"), render_wps_user_page),
    ]
    for function, parsed, renderer in handlers:
        handler = FakeHandler()
        kwargs = {
            "require_admin": lambda _parsed: True,
            "wps_connect": connect,
            "wps_lock": lock,
            "csrf_input": lambda token: f"csrf={token}",
            "render_page": renderer,
        }
        if function in {handle_overview, handle_users, handle_devices, handle_user}:
            kwargs["now_func"] = lambda: 1100
        if function is handle_user:
            function(handler, parsed, registered["user"]["id"], **kwargs)
        else:
            function(handler, parsed, **kwargs)
        assert handler.responses and handler.responses[0][1] == "text/html; charset=utf-8"
        assert "DocxTool 管理工作台" in handler.responses[0][0]


def test_admin_user_route_returns_a_drawer_fragment_when_requested(tmp_path):
    _path, connect, lock, registered = _seed(tmp_path)

    class FakeHandler:
        def __init__(self):
            self.responses = []

        def _admin_csrf_token(self, _parsed):
            return "csrf"

        def _text(self, body, mime):
            self.responses.append((body, mime))

        def send_error(self, status):
            self.responses.append(("error", status))

    handler = FakeHandler()
    handle_user(
        handler,
        SimpleNamespace(query="drawer=1"),
        registered["user"]["id"],
        require_admin=lambda _parsed: True,
        wps_connect=connect,
        wps_lock=lock,
        now_func=lambda: 1100,
        csrf_input=lambda token: f"csrf={token}",
        render_page=render_wps_user_page,
    )

    html, mime = handler.responses[0]
    assert mime == "text/html; charset=utf-8"
    assert "data-user-detail-drawer" in html
    assert "当前设备" in html
    assert "DocxTool 管理工作台" not in html
