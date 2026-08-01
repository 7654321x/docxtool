from __future__ import annotations

from docxtool.web.monitor_dashboard_page import render_monitor_dashboard_html


def test_render_monitor_dashboard_html_uses_injected_stats_and_fragments() -> None:
    """仪表盘整页渲染器应使用注入统计数据、局部 HTML 和运行状态。"""
    stats = {
        "total": 3,
        "done": 2,
        "error": 1,
        "rate": 66,
        "avg_s": 4,
        "unique_ips": 2,
        "recent": [{"id": "t1"}],
        "recent_total": 1,
        "ip_total": 1,
        "banned_ips": [{"ip": "127.0.0.1"}],
        "trend": [{"day": "2026-08-02"}],
        "query": {"recent_size": 20, "ip_size": 10},
    }

    html = render_monitor_dashboard_html(
        stats,
        "csrf-token",
        limit_settings=lambda: {"enabled": True, "window_seconds": 60, "count": 5},
        csrf_hidden_input=lambda token: f"<input value='{token}'>",
        normalize_monitor_query=lambda: {"recent_size": 50, "ip_size": 50},
        pager_html=lambda _stats, _token, page_key, _pages_key: f"<nav>{page_key}</nav>",
        ready_payload=lambda: {"ok": True, "checks": {"database": True}},
        version_payload=lambda: {
            "version": "2.3",
            "queued": 0,
            "processing": 1,
            "max_workers": 4,
            "max_queue": 8,
            "max_upload_mb": 10,
            "process_timeout_seconds": 60,
        },
        render_recent_task_rows=lambda *_args: ["<tr><td>任务行</td></tr>"],
        render_top_ip_rows=lambda *_args: "<tr><td>IP 行</td></tr>",
        render_banned_ip_rows=lambda *_args: "<tr><td>封禁行</td></tr>",
        render_trend_bars=lambda _trend: "<div>趋势</div>",
        render_health_check_items=lambda _ready: "<li>健康</li>",
        admin_url=lambda path, **_kwargs: path,
        html_escape=lambda value: value.replace("<", "&lt;"),
        now_local=lambda: "2026-08-02 05:30:00",
        max_monitor_page_size=100,
    )

    assert "ADMIN WORKSPACE / 2.3" in html
    assert "任务行" in html
    assert "IP 行" in html
    assert "封禁行" in html
    assert "限额已开启" in html
    assert "最近任务/页" in html
    assert "max=\"100\"" in html
    assert "最后生成：2026-08-02 05:30:00" in html
