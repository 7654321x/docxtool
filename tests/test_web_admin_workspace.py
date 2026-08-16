from types import SimpleNamespace

from docxtool.web.admin_workspace_page import (
    render_admin_home_page,
    render_admin_web_ip_detail_page,
    render_admin_web_page,
    render_admin_web_task_log_page,
    render_wps_devices_page,
    render_wps_overview_page,
    render_wps_tasks_page,
    render_wps_user_page,
    render_wps_users_page,
)
from docxtool.web.admin_workspace_routes import (
    handle_web_page,
    ip_compat_target,
    log_compat_target,
    monitor_compat_target,
    task_id_from_query,
    workspace_session_target,
)
from docxtool.web.admin_shell import render_admin_shell
from docxtool.web.routing import match_get_route, match_post_route


def _user_page() -> dict:
    return {
        "rows": [
            {
                "id": "wusr_1",
                "username": "User01",
                "status": "active",
                "created_at": 1000,
                "last_login_at": 2000,
                "device_count": 1,
                "online": 1,
                "format_total": 2,
                "format_success": 1,
                "format_failed": 0,
                "format_pending": 1,
                "last_format_at": 3000,
                "app_version": "5.1",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
    }


def test_admin_workspace_routes_are_explicit():
    assert match_get_route("/admin").action == "admin_workspace"
    assert match_get_route("/admin/web").action == "admin_web"
    assert match_get_route("/admin/web/security").value == "security"
    assert match_get_route("/admin/wps").action == "admin_wps_overview"
    assert match_get_route("/admin/wps/users").action == "admin_wps_users"
    assert match_get_route("/admin/wps/devices").action == "admin_wps_devices"
    assert match_get_route("/admin/wps/tasks").action == "admin_wps_tasks"
    user_route = match_get_route("/admin/wps/users/wusr_1")
    assert user_route.action == "admin_wps_user"
    assert user_route.value == "wusr_1"
    assert match_get_route("/admin/wps/users/wusr_1/extra").action == "not_found"
    assert match_post_route("/admin/wps/users/wusr_1/status").action == "admin_wps_user_status"
    assert match_post_route("/admin/wps/users/wusr_1/password").action == "admin_wps_user_password_reset"
    assert match_post_route("/admin/wps/users/wusr_1/notifications").action == "admin_wps_user_notification"
    assert match_post_route("/admin/wps/users/wusr_1/delete").action == "admin_wps_user_delete"
    assert match_post_route("/admin/wps/devices/wdev_1/status").action == "admin_wps_device_status"


def test_workspace_navigation_keeps_web_and_wps_submenus_visible() -> None:
    """两个业务模块的二级菜单应同时显示，仅当前模块高亮对应页面。"""
    page = render_admin_shell(
        title="WPS 排版任务",
        active_module="wps",
        active_page="tasks",
        body="",
        csrf_input="",
    )

    assert page.count('class="secondary-nav-list"') == 2
    assert '<a class="secondary-nav" href="/admin/web/tasks">任务中心</a>' in page
    assert '<a class="secondary-nav active" href="/admin/wps/tasks">排版任务</a>' in page


def test_legacy_workspace_targets_keep_only_supported_detail_and_filter_state():
    parsed = SimpleNamespace(query="ignored=1")

    assert monitor_compat_target(
        parsed,
        monitor_query_from=lambda _parsed: {
            "task_q": "report & plan",
            "task_status": "done",
            "recent_page": 2,
            "recent_size": 50,
        },
    ) == "/admin/web/tasks?q=report+%26+plan&status=done&page=2&page_size=50"
    assert ip_compat_target("2001:db8::1") == "/admin/web/security?ip=2001%3Adb8%3A%3A1"
    assert log_compat_target("task-1") == "/admin/web/logs?task_id=task-1"
    assert task_id_from_query(SimpleNamespace(query="task_id=task-1&next=https%3A%2F%2Fbad.example")) == "task-1"
    assert workspace_session_target(
        SimpleNamespace(
            path="/admin/wps/users/wusr_1",
            query="tab=security&page=2&token=legacy&next=https%3A%2F%2Fbad.example",
        )
    ) == "/admin/wps/users/wusr_1?tab=security&page=2"
    assert workspace_session_target(
        SimpleNamespace(
            path="/admin/web/tasks",
            query="q=report&status=done&page=2&page_size=50&admin_token=legacy",
        )
    ) == "/admin/web/tasks?q=report&status=done&page=2&page_size=50"


def test_admin_workspace_shell_keeps_three_primary_modules_and_true_metrics():
    home = render_admin_home_page(
        web_summary={"total": 3, "done": 2, "error": 1, "queued": 4},
        wps_summary={"users": 4, "online_devices": 1, "requests": 5, "pending": 1},
        readiness={"ok": True},
        csrf_input='<input name="csrf_token" value="csrf">',
    )

    for href in ("/admin", "/admin/web/tasks", "/admin/wps"):
        assert f'href="{href}"' in home
    for label in (
        "网页任务总数",
        "网页成功任务",
        "网页失败任务",
        "网页当前排队",
        "WPS 用户数",
        "WPS 在线设备",
        "WPS 排版请求",
        "WPS 待回报",
    ):
        assert label in home
    assert "显示名称" not in home


def test_wps_user_list_uses_a_direct_detail_link_and_progressive_drawer():
    users = render_wps_users_page(
        result=_user_page(),
        filters={"q": "", "status": "", "online": "", "version": "", "page": 1, "page_size": 20},
        csrf_input="",
    )

    assert "注册时间" in users
    assert "最后登录" in users
    assert "搜索登录账号" in users
    assert 'data-user-drawer-url="/admin/wps/users/wusr_1?drawer=1"' in users
    assert ">详情</a>" in users
    assert 'id="wps-user-drawer-root"' in users
    assert "data-action-menu" not in users
    assert 'action="/admin/wps/users/wusr_1/status"' not in users
    assert "重置密码" not in users
    assert users.count("1970-01-01") >= 2


def test_wps_overview_devices_tasks_and_user_tabs_render_only_real_data():
    overview = render_wps_overview_page(
        summary={"users": 1, "online_devices": 1, "requests": 1, "pending": 0, "success": 1, "failed": 0, "average_duration_ms": 120},
        trend=[{"date": "2026-08-15", "total": 1, "success": 1, "failed": 0}],
        recent=[{"requested_at": 1000, "username": "User01", "device_name": "测试电脑", "command": "format", "status": "success", "duration_ms": 120}],
        csrf_input="",
    )
    devices = render_wps_devices_page(
        result={"rows": [{"user_id": "wusr_1", "username": "User01", "device_name": "测试电脑", "platform": "windows", "app_version": "5.1", "status": "active", "online": 1, "last_seen_at": 1000, "format_total": 1}], "total": 1, "page": 1, "page_size": 20},
        filters={"q": "", "status": "", "online": "", "version": "", "page": 1, "page_size": 20},
        csrf_input="",
    )
    tasks = render_wps_tasks_page(
        result={"rows": [{"requested_at": 1000, "request_id": "request-1", "document_name": "通知.docx", "username": "User01", "device_name": "测试电脑", "command": "format", "status": "success", "config_version": "config-1", "duration_ms": 120, "error_code": "", "app_version": "5.1"}], "total": 1, "page": 1, "page_size": 20},
        filters={"q": "", "status": "", "online": "", "version": "", "page": 1, "page_size": 20},
        csrf_input="",
    )
    user = render_wps_user_page(
        detail={"user": {"id": "wusr_1", "username": "User01", "status": "active", "created_at": 1000, "last_login_at": 2000}, "summary": {"device_count": 1, "online_devices": 1, "format_total": 1, "format_success": 1, "format_failed": 0, "format_pending": 0}},
        tab="security",
        result=None,
        filters={"page": 1, "page_size": 20},
        csrf_input="",
    )

    assert "近 7 天趋势" in overview
    assert "暂无趋势数据" not in overview
    assert "设备管理" in devices and "测试电脑" in devices
    assert "WPS 排版任务" in tasks and "request-1" in tasks
    assert "<th>文件名</th>" in tasks and "通知.docx" in tasks
    assert "<th>配置</th>" not in tasks
    assert "config-1" not in tasks
    assert "<th>版本</th>" in tasks and "5.1" in tasks
    assert "WPS 管理写操作尚未启用" in user
    assert 'action="/admin/wps/users/wusr_1/status"' not in user


def test_wps_phase_b_controls_and_audit_logs_are_visible_only_when_the_gate_is_enabled():
    filters = {"q": "", "status": "", "online": "", "version": "", "page": 1, "page_size": 20}
    detail = {
        "user": {"id": "wusr_1", "username": "User01", "status": "active", "created_at": 1000, "last_login_at": 2000},
        "summary": {},
    }
    disabled = render_wps_user_page(
        detail=detail,
        tab="security",
        result=None,
        filters=filters,
        csrf_input='<input name="csrf_token" value="csrf">',
    )
    enabled = render_wps_user_page(
        detail=detail,
        tab="security",
        result=None,
        filters=filters,
        csrf_input='<input name="csrf_token" value="csrf">',
        mutations_enabled=True,
    )
    users = render_wps_users_page(
        result=_user_page(),
        filters=filters,
        csrf_input='<input name="csrf_token" value="csrf">',
        mutations_enabled=True,
    )
    logs = render_wps_user_page(
        detail=detail,
        tab="logs",
        result=None,
        audit_result={
            "rows": [
                {"created_at": 1000, "event": "wps.admin.user.password_reset", "result": "success", "error_code": "", "actor_type": "session"}
            ],
            "total": 1,
            "page": 1,
            "page_size": 20,
        },
        filters=filters,
        csrf_input="",
    )
    devices = render_wps_devices_page(
        result={"rows": [{"id": "wdev_1", "user_id": "wusr_1", "username": "User01", "device_name": "测试电脑", "platform": "windows", "app_version": "5.1", "status": "active", "online": 1, "last_seen_at": 1000, "format_total": 1}], "total": 1, "page": 1, "page_size": 20},
        filters=filters,
        csrf_input='<input name="csrf_token" value="csrf">',
        mutations_enabled=True,
    )

    assert 'action="/admin/wps/users/wusr_1/status"' not in disabled
    for action in ("/admin/wps/users/wusr_1/status", "/admin/wps/users/wusr_1/password", "/admin/wps/users/wusr_1/notifications", "/admin/wps/users/wusr_1/delete"):
        assert f'action="{action}"' in enabled
    assert 'action="/admin/wps/devices/wdev_1/status"' in devices
    assert 'action="/admin/wps/users/wusr_1/status"' not in users
    assert 'data-user-drawer-url="/admin/wps/users/wusr_1?drawer=1"' in users
    assert '<form method="post" action="/admin/wps/users/wusr_1/' not in users
    assert "密码已重置" in logs
    assert "session-token" not in logs


def test_wps_user_drawer_uses_only_real_overview_data_and_omits_deferred_cards():
    drawer = render_wps_user_page(
        detail={
            "user": {
                "id": "wusr_1",
                "username": "User01",
                "status": "active",
                "created_at": 1000,
                "last_login_at": 2000,
            },
            "summary": {
                "device_count": 1,
                "online_devices": 1,
                "format_total": 6,
                "format_success": 5,
                "format_failed": 1,
                "format_pending": 0,
                "average_duration_ms": 1540,
            },
            "current_device": {
                "device_name": "测试电脑",
                "platform": "Windows 11",
                "app_version": "5.4.3",
                "status": "active",
                "online": 1,
                "last_seen_at": 3000,
            },
        },
        tab="overview",
        result=None,
        filters={"page": 1, "page_size": 20},
        csrf_input="",
        drawer=True,
    )

    assert 'data-user-detail-drawer' in drawer
    for label in ("账号状态", "当前设备", "插件信息", "使用统计", "测试电脑", "5.4.3", "1.54 秒"):
        assert label in drawer
    for deferred in ("最近任务", "基本信息", "安全风险"):
        assert deferred not in drawer


def test_web_pages_render_task_filter_security_and_log_links_without_unescaped_input():
    stats = {
        "total": 1,
        "done": 1,
        "error": 0,
        "rate": 100,
        "recent_total": 1,
        "recent_page": 1,
        "recent_pages": 1,
        "query": {"task_q": "<report>", "task_status": "done", "recent_page": 1, "recent_size": 20},
        "recent": [{"created_at": "2026-08-15", "id": "task-1", "filename": "<report>.docx", "status": "done", "doc_type": "NORMAL", "paragraphs": 2, "duration_ms": 1000, "error_code": ""}],
        "top_ips": [{"ip": "203.0.113.1", "c": 1, "done": 1, "error": 0, "last": "2026-08-15"}],
        "banned_ips": [],
        "unique_ips": 1,
        "total_mb": 1.0,
        "avg_s": 1.0,
    }
    task_html = render_admin_web_page(section="tasks", stats=stats, query=stats["query"], readiness={"ok": True}, runtime={}, limit={}, csrf_input="")
    security_html = render_admin_web_page(section="security", stats=stats, query=stats["query"], readiness={"ok": True}, runtime={}, limit={}, csrf_input='<input name="csrf_token">')
    log_html = render_admin_web_page(section="logs", stats=stats, query=stats["query"], readiness={"ok": True}, runtime={}, limit={}, csrf_input="")

    assert "&lt;report&gt;.docx" in task_html
    assert "<report>.docx" not in task_html
    assert 'href="/admin/web/logs?task_id=task-1"' in log_html
    assert 'href="/admin/web/security?ip=203.0.113.1"' in security_html
    assert 'action="/ban"' in security_html


def test_web_ip_and_log_details_use_shared_shell_and_escape_content():
    ip_html = render_admin_web_ip_detail_page(
        ip="203.0.113.1",
        activity=[
            {
                "id": "task-1",
                "created_at": "2026-08-15",
                "filename": "<report>.docx",
                "file_size": 2048,
                "paragraphs": 2,
                "duration_ms": 1200,
                "status": "done",
            }
        ],
        total=2,
        last_hour=1,
        banned=False,
        csrf_input='<input name="csrf_token">',
        readiness={"ok": True},
    )
    log_html = render_admin_web_task_log_page(
        task_id="task-1",
        row={"filename": "<report>.docx", "status": "done", "created_at": "2026-08-15", "duration_ms": 1200, "error_code": ""},
        log_text="<secret>",
        readiness={"ok": True},
    )

    assert "DocxTool 管理工作台" in ip_html
    assert 'href="/admin/web/logs?task_id=task-1"' in ip_html
    assert "&lt;report&gt;.docx" in ip_html
    assert "<report>.docx" not in ip_html
    assert "日志查询 · 任务详情" in log_html
    assert "&lt;secret&gt;" in log_html
    assert "<secret>" not in log_html


def test_web_workspace_route_keeps_section_and_filter_ownership_in_one_handler():
    class FakeHandler:
        def __init__(self):
            self.responses = []

        def _admin_csrf_token(self, _parsed):
            return "csrf"

        def _text(self, body, mime):
            self.responses.append((body, mime))

    handler = FakeHandler()
    captured = {}

    def render_page(**kwargs):
        captured.update(kwargs)
        return "rendered"

    handle_web_page(
        handler,
        SimpleNamespace(query="q=report&status=done&page=2&page_size=50"),
        "logs",
        require_admin=lambda _parsed: True,
        monitor_query_from=lambda _parsed: {"recent_page": 1, "recent_size": 20, "ip_page": 1, "ip_size": 20},
        web_stats=lambda query: {"query": query},
        readiness=lambda: {"ok": True},
        runtime=lambda: {"queued": 0},
        limit_settings=lambda: {"enabled": True},
        csrf_input=lambda token: f"csrf={token}",
        render_page=render_page,
    )

    assert handler.responses == [("rendered", "text/html; charset=utf-8")]
    assert captured["section"] == "logs"
    assert captured["query"]["task_q"] == "report"
    assert captured["query"]["task_status"] == "done"
    assert captured["query"]["recent_page"] == "2"
    assert captured["query"]["recent_size"] == "50"
