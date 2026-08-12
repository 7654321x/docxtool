from docxtool.web.admin_workspace_page import render_admin_home_page, render_wps_users_page
from docxtool.web.routing import match_get_route, match_post_route


def test_admin_workspace_routes_are_explicit():
    assert match_get_route("/admin").action == "admin_workspace"
    assert match_get_route("/admin/web").action == "admin_web"
    assert match_get_route("/admin/wps/users").action == "admin_wps_users"
    user_route = match_get_route("/admin/wps/users/wusr_1")
    assert user_route.action == "admin_wps_user"
    assert user_route.value == "wusr_1"
    assert match_get_route("/admin/wps/users/wusr_1/extra").action == "not_found"
    assert match_post_route("/admin/wps/users/wusr_1/status").action == "admin_wps_user_status"
    assert match_post_route("/admin/wps/devices/wdev_1/status").action == "admin_wps_device_status"
def test_admin_workspace_pages_link_web_and_wps_modules():
    home = render_admin_home_page(
        web_summary={"total": 3, "done": 2, "error": 1, "queued": 4},
        wps_summary={"users": 4, "online_devices": 1, "requests": 5, "pending": 1},
        readiness={"ok": True},
        csrf_input='<input name="csrf_token" value="csrf">',
    )
    users = render_wps_users_page(rows=[], query="", status="", csrf_input="")

    assert "/admin/web" in home
    assert "/admin/wps/users" in home
    for label in (
        "网页任务总数",
        "网页成功任务",
        "网页失败任务",
        "网页当前排队",
        "WPS 用户数",
        "WPS 在线设备",
        "WPS 排版请求总数",
        "WPS 待回报数",
    ):
        assert label in home
    assert "WPS 用户" in users


def test_wps_user_list_includes_registration_and_last_login_times():
    users = render_wps_users_page(
        rows=[
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
        query="",
        status="",
        csrf_input="",
    )

    assert "注册时间" in users
    assert "最后登录" in users
    assert "显示名称" not in users
    assert "搜索登录账号" in users
    assert users.count("1970-01-01") >= 2
