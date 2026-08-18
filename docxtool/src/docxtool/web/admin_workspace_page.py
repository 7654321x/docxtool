"""Compatibility facade for the split administrator workspace renderers."""

from __future__ import annotations

from .admin_shell import render_admin_shell
from .admin_web_pages import (
    render_admin_web_ip_detail_page,
    render_admin_web_page,
    render_admin_web_task_log_page,
)
from .admin_wps_pages import (
    render_wps_devices_page,
    render_wps_overview_page,
    render_wps_tasks_page,
    render_wps_user_page,
    render_wps_users_page,
)


def render_admin_home_page(*, web_summary: dict, wps_summary: dict, readiness: dict, csrf_input: str) -> str:
    """Render the cross-product overview using the shared shell."""
    body = f"""<div class="metric-grid"><div class="metric"><b>{int(web_summary.get('total', 0) or 0)}</b><span>网页任务总数</span></div><div class="metric good"><b>{int(web_summary.get('done', 0) or 0)}</b><span>网页成功任务</span></div><div class="metric bad"><b>{int(web_summary.get('error', 0) or 0)}</b><span>网页失败任务</span></div><div class="metric"><b>{int(web_summary.get('queued', 0) or 0)}</b><span>网页当前排队</span></div><div class="metric"><b>{int(wps_summary.get('users', 0) or 0)}</b><span>WPS 用户数</span></div><div class="metric"><b>{int(wps_summary.get('online_devices', 0) or 0)}</b><span>WPS 在线设备</span></div><div class="metric"><b>{int(wps_summary.get('requests', 0) or 0)}</b><span>WPS 排版请求</span></div><div class="metric"><b>{int(wps_summary.get('pending', 0) or 0)}</b><span>WPS 待回报</span></div></div><section class="panel"><div class="panel-head"><div><h2>服务状态</h2><p>网页业务库与 WPS 插件库保持独立，仅在页面应用层汇总。</p></div><a class="button" href="/admin/web/tasks">查看网页任务</a></div></section>"""
    return render_admin_shell(
        title="综合概览",
        active_module="home",
        body=body,
        csrf_input=csrf_input,
        service_status={"web": bool(readiness.get("ok")), "wps_data": True},
    )


__all__ = (
    "render_admin_home_page",
    "render_admin_shell",
    "render_admin_web_ip_detail_page",
    "render_admin_web_page",
    "render_admin_web_task_log_page",
    "render_wps_devices_page",
    "render_wps_overview_page",
    "render_wps_tasks_page",
    "render_wps_user_page",
    "render_wps_users_page",
)
