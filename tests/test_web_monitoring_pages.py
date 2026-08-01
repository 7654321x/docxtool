from docxtool.web.monitoring_pages import (
    render_banned_ip_rows,
    render_health_check_items,
    render_ip_detail_html,
    render_pager_html,
    render_recent_task_rows,
    render_task_log_html,
    render_top_ip_rows,
    render_trend_bars,
    status_badge,
)


def test_render_pager_html_preserves_monitor_query_and_boundary_classes():
    stats = {
        "query": {
            "recent_page": 2,
            "recent_size": 20,
            "recent_pages": 3,
            "ip_page": 1,
            "ip_size": 10,
            "ip_pages": 1,
        },
        "recent_page": 2,
        "recent_pages": 3,
    }

    html = render_pager_html(stats, "csrf-token", "recent_page", "recent_pages")

    assert "第 2 / 3 页" in html
    assert "recent_page=1" in html
    assert "recent_page=3" in html
    assert "recent_size=20" in html
    assert "ip_size=10" in html


def test_status_badge_maps_known_and_unknown_statuses():
    assert status_badge("done") == ("完成", "done")
    assert status_badge("queued") == ("排队中", "queued")
    assert status_badge("custom") == ("custom", "processing")


def test_render_recent_task_rows_escapes_filename_and_links_log():
    rows = render_recent_task_rows(
        {
            "recent": [{
                "id": "task-1",
                "created_at": "2026-08-02 10:00:00",
                "filename": "<report>.docx",
                "ip": "203.0.113.8",
                "file_size": 2048,
                "doc_type": "NORMAL",
                "paragraphs": 5,
                "duration_ms": 1200,
                "status": "done",
            }]
        },
        "csrf-token",
        lambda path, token: f"/admin{path}?csrf={token}",
    )

    assert "&lt;report&gt;.docx" in rows
    assert "<report>.docx" not in rows
    assert "/admin/log/task-1?csrf=csrf-token" in rows
    assert "完成" in rows


def test_render_ip_tables_and_trend_fragments():
    stats = {
        "top_ips": [{
            "ip": "203.0.113.8",
            "c": 2,
            "done": 1,
            "error": 1,
            "last": "2026-08-02 11:00:00",
            "last_filename": "<latest>.docx",
        }],
        "banned_ips": [{
            "ip": "203.0.113.9",
            "reason": "<blocked>",
            "created_at": "2026-08-02 11:30:00",
        }],
    }

    top_rows = render_top_ip_rows(stats, "csrf-token", '<input name="csrf">', lambda path, token: f"/admin{path}?csrf={token}")
    banned_rows = render_banned_ip_rows(stats, '<input name="csrf">')
    trend = render_trend_bars([{"date": "2026-08-01", "done": 2, "error": 1, "total": 3}])
    empty_trend = render_trend_bars([])
    checks = render_health_check_items({"checks": {"database": True, "output_dir": False, "log_dir": True}})

    assert "&lt;latest&gt;.docx" in top_rows
    assert "addr=203.0.113.8" in top_rows
    assert "&lt;blocked&gt;" in banned_rows
    assert "2026-08-01" in trend
    assert "暂无趋势数据" in empty_trend
    assert "数据库" in checks
    assert "异常" in checks


def test_render_task_log_html_escapes_log_and_task_metadata():
    html = render_task_log_html(
        "task-<1>",
        {
            "filename": "<report>.docx",
            "status": "error",
            "duration_ms": 2500,
            "error_code": "DOCX_ERROR",
            "created_at": "2026-08-02 10:30:00",
        },
        "line <script>alert(1)</script>",
    )

    assert "任务日志" in html
    assert "TASK LOG / task-&lt;1&gt;" in html
    assert "&lt;report&gt;.docx" in html
    assert "<report>.docx" not in html
    assert "2.5s" in html
    assert "DOCX_ERROR" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_render_ip_detail_html_uses_injected_callbacks_and_escapes_values():
    calls = []

    def csrf_hidden_input(token: str) -> str:
        calls.append(("csrf", token))
        return '<input name="csrf_token" value="token">'

    def ip_activity(ip: str) -> list:
        calls.append(("activity", ip))
        return [{
            "id": "task-1",
            "created_at": "2026-08-02 10:00:00",
            "filename": "<bad>.docx",
            "file_size": 2048,
            "paragraphs": 3,
            "duration_ms": 1500,
            "status": "done",
        }]

    def ip_upload_count(ip: str, window_seconds: int) -> int:
        calls.append(("count", ip, window_seconds))
        return 7 if window_seconds == 0 else 2

    def is_ip_banned(ip: str) -> bool:
        calls.append(("banned", ip))
        return False

    def admin_url(path: str, token: str) -> str:
        calls.append(("url", path, token))
        return f"/admin{path}?csrf={token}"

    html = render_ip_detail_html(
        "203.0.113.9",
        "csrf-1",
        csrf_hidden_input=csrf_hidden_input,
        ip_activity=ip_activity,
        ip_upload_count=ip_upload_count,
        is_ip_banned=is_ip_banned,
        admin_url=admin_url,
    )

    assert "IP 上传明细" in html
    assert "&lt;bad&gt;.docx" in html
    assert "<bad>.docx" not in html
    assert "总上传次数" in html
    assert "最近 1 小时" in html
    assert 'action="/ban"' in html
    assert ("count", "203.0.113.9", 0) in calls
    assert ("count", "203.0.113.9", 3600) in calls
