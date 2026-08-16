"""Server-rendered WPS administration pages with gate-controlled Phase B actions."""

from __future__ import annotations

import html
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import quote, urlencode

from .admin_shell import render_admin_shell


_ENTITY_STATUS_OPTIONS = (("", "全部"), ("active", "正常"), ("disabled", "停用"))
_REQUEST_STATUS_OPTIONS = (("", "全部"), ("authorized", "待回报"), ("success", "成功"), ("failed", "失败"))


def _escape(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _time(value: object) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return "-"


def _status(value: object) -> tuple[str, str]:
    raw = str(value or "")
    mapping = {
        "active": ("正常", "good"),
        "disabled": ("停用", "bad"),
        "authorized": ("待回报", "pending"),
        "success": ("成功", "good"),
        "failed": ("失败", "bad"),
        "denied": ("已拒绝", "bad"),
    }
    return mapping.get(raw, (raw or "-", "info"))


def _page_url(path: str, filters: Mapping[str, object], **overrides: object) -> str:
    values = {
        "q": str(filters.get("q", "") or ""),
        "status": str(filters.get("status", "") or ""),
        "online": str(filters.get("online", "") or ""),
        "version": str(filters.get("version", "") or ""),
        "page": str(filters.get("page", 1) or 1),
        "page_size": str(filters.get("page_size", 20) or 20),
    }
    if filters.get("tab"):
        values["tab"] = str(filters["tab"])
    values.update({key: str(value) for key, value in overrides.items()})
    values = {key: value for key, value in values.items() if value and not (key == "page" and value == "1")}
    encoded = urlencode(values)
    return path + (f"?{encoded}" if encoded else "")


def _pager(path: str, result: Mapping[str, object], filters: Mapping[str, object]) -> str:
    page = int(result.get("page", 1) or 1)
    page_size = int(result.get("page_size", 20) or 20)
    total = int(result.get("total", 0) or 0)
    pages = max(1, (total + page_size - 1) // page_size)
    previous = _page_url(path, filters, page=max(1, page - 1))
    following = _page_url(path, filters, page=min(pages, page + 1))
    return (
        f'<div class="pager"><span>共 {total} 条，第 {page} / {pages} 页</span>'
        f'<a class="{"disabled" if page <= 1 else ""}" href="{_escape(previous)}">上一页</a>'
        f'<a class="{"disabled" if page >= pages else ""}" href="{_escape(following)}">下一页</a></div>'
    )


def _filters(
    path: str,
    filters: Mapping[str, object],
    *,
    online: bool = False,
    version: bool = False,
    placeholder: str = "账号、设备或请求编号",
    request_status: bool = False,
) -> str:
    online_field = ""
    if online:
        current = str(filters.get("online", "") or "")
        online_field = f"""<label>在线<select name="online"><option value="">全部</option><option value="online"{' selected' if current == 'online' else ''}>在线</option><option value="offline"{' selected' if current == 'offline' else ''}>离线</option></select></label>"""
    version_field = ""
    if version:
        version_field = f'<label>版本<input name="version" value="{_escape(filters.get("version", ""))}" placeholder="插件版本"></label>'
    current_status = str(filters.get("status", "") or "")
    status_options = _REQUEST_STATUS_OPTIONS if request_status else _ENTITY_STATUS_OPTIONS
    status_field = "".join(
        f'<option value="{value}"{" selected" if value == current_status else ""}>{label}</option>'
        for value, label in status_options
    )
    return f"""<form class="filter-form" method="get" action="{_escape(path)}"><label>关键词<input name="q" value="{_escape(filters.get('q', ''))}" placeholder="{_escape(placeholder)}"></label><label>状态<select name="status">{status_field}</select></label>{online_field}{version_field}<label>每页<select name="page_size"><option value="20"{' selected' if int(filters.get('page_size', 20)) == 20 else ''}>20</option><option value="50"{' selected' if int(filters.get('page_size', 20)) == 50 else ''}>50</option><option value="100"{' selected' if int(filters.get('page_size', 20)) == 100 else ''}>100</option></select></label><button class="button primary" type="submit">查询</button><a class="button" href="{_escape(path)}">清除</a></form>"""


def _user_url(user_id: object, *, tab: str = "", drawer: bool = False) -> str:
    """Build one safe canonical user-detail URL for full-page and drawer navigation."""
    path = f"/admin/wps/users/{quote(str(user_id or ''), safe='')}"
    values: dict[str, str] = {}
    if drawer:
        values["drawer"] = "1"
    if tab and tab != "overview":
        values["tab"] = tab
    return path + (f"?{urlencode(values)}" if values else "")


def _drawer_link(user_id: object, label: str, *, tab: str = "overview", danger: bool = False) -> str:
    """Keep a normal detail-page fallback while making the same link drawer-aware."""
    classes = "drawer-action danger" if danger else "drawer-action"
    return (
        f'<a class="{classes}" href="{_escape(_user_url(user_id, tab=tab))}" '
        f'data-user-drawer-url="{_escape(_user_url(user_id, tab=tab, drawer=True))}">{_escape(label)}</a>'
    )


def _user_tabs(user_id: object, tab: str, *, drawer: bool) -> str:
    """Render the same tab model for a full user page and the progressive drawer."""
    tabs = (
        ("overview", "概览"),
        ("devices", "设备"),
        ("tasks", "任务"),
        ("logs", "日志"),
        ("security", "安全"),
    )
    links = []
    for key, label in tabs:
        href = _user_url(user_id, tab=key)
        drawer_url = _user_url(user_id, tab=key, drawer=True)
        drawer_attribute = f' data-user-drawer-url="{_escape(drawer_url)}"' if drawer else ""
        links.append(
            f'<a class="tab{" active" if key == tab else ""}" href="{_escape(href)}"{drawer_attribute}>{label}</a>'
        )
    return "".join(links)


def _duration(value: object) -> str:
    """Present a real persisted duration without inventing a value for missing data."""
    try:
        milliseconds = max(0, int(value))
    except (TypeError, ValueError):
        return "-"
    if not milliseconds:
        return "-"
    seconds = f"{milliseconds / 1000:.2f}".rstrip("0").rstrip(".")
    return f"{seconds} 秒"


_USER_DETAIL_STYLE = """
<style>
body.user-drawer-open{overflow:hidden}.user-detail-link{color:var(--blue);font-weight:650}.user-detail-link:hover{color:#dbeafe;text-decoration:underline}
.user-drawer-overlay{position:fixed;inset:0;z-index:20;display:flex;justify-content:flex-end;background:rgba(1,8,18,.48)}.user-detail-drawer{width:min(46vw,860px);min-width:560px;height:100dvh;display:flex;flex-direction:column;overflow:hidden;border-left:1px solid var(--line);background:#09172a;box-shadow:-22px 0 52px rgba(0,0,0,.35);outline:0}.user-drawer-header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:17px 18px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,rgba(18,35,59,.94),rgba(9,23,42,.94))}.user-drawer-header h2{margin:0;font-size:17px}.user-drawer-close{display:grid;place-items:center;width:30px;height:30px;border:1px solid var(--line);border-radius:7px;background:rgba(255,255,255,.03);color:#c8d6e9;font-size:20px;line-height:1}.user-drawer-close:hover{border-color:rgba(246,200,95,.42);color:#ffe7a4}.user-drawer-scroll{overflow:auto;padding:14px 16px 24px}.user-summary{padding:15px;border:1px solid var(--line);border-radius:10px;background:linear-gradient(145deg,rgba(18,35,59,.9),rgba(10,24,42,.9))}.user-summary-top{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.user-identity{display:flex;align-items:center;gap:11px;min-width:0}.user-avatar{display:grid;flex:0 0 auto;place-items:center;width:37px;height:37px;border-radius:50%;background:linear-gradient(135deg,#355273,#182a45);color:#eff6ff;font-weight:800}.user-identity h3{margin:0;font-size:16px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.user-identity .status-tag{margin-top:5px}.user-summary-meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px 14px;margin:13px 0 0}.user-summary-meta div{min-width:0;color:var(--muted);font-size:10px}.user-summary-meta b{display:block;margin-top:3px;color:#c8d6e9;font-size:11px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.user-summary-actions{display:flex;justify-content:flex-end;gap:6px;flex-wrap:wrap;margin-top:13px}.drawer-action{display:inline-flex;align-items:center;justify-content:center;min-height:30px;padding:0 9px;border:1px solid var(--line);border-radius:6px;background:rgba(255,255,255,.03);color:#c8d6e9;font-size:11px}.drawer-action:hover{border-color:rgba(246,200,95,.42);color:#ffe7a4}.drawer-action.danger{border-color:rgba(251,113,133,.35);color:#fecdd3}.drawer-tabs{display:flex;gap:3px;overflow:auto;margin:14px -16px 0;padding:0 16px;border-bottom:1px solid var(--line)}.drawer-tabs .tab{flex:0 0 auto;border-radius:7px 7px 0 0}.drawer-content{padding-top:14px}.detail-overview-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.detail-card{min-width:0;padding:13px;border:1px solid rgba(160,181,215,.14);border-radius:9px;background:rgba(255,255,255,.025)}.detail-card h3{margin:0 0 12px;font-size:13px}.detail-card strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:15px}.detail-card .hint{margin-top:3px}.detail-facts{display:grid;gap:8px;margin:12px 0 0}.detail-facts div{display:flex;align-items:baseline;justify-content:space-between;gap:8px;color:var(--muted);font-size:11px}.detail-facts b{min-width:0;color:#c8d6e9;font-size:11px;font-weight:600;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.detail-facts .ok{color:var(--green)}.detail-facts .bad{color:#ff9cab}.usage-section{margin-top:12px;padding:13px;border:1px solid rgba(160,181,215,.14);border-radius:9px;background:rgba(255,255,255,.02)}.usage-section h3{margin:0 0 11px;font-size:13px}.usage-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.usage-metric{min-width:0;padding:10px;border-radius:7px;background:rgba(18,35,59,.8)}.usage-metric b{display:block;font-size:19px}.usage-metric span{display:block;margin-top:4px;color:var(--muted);font-size:10px}.usage-metric.good b{color:var(--green)}.usage-metric.bad b{color:#ff9cab}.drawer-empty{padding:24px 14px;color:var(--muted);font-size:12px;text-align:center}
@media(max-width:780px){.user-detail-drawer{width:100%;min-width:0}.user-drawer-scroll{padding:12px}.drawer-tabs{margin-left:-12px;margin-right:-12px;padding-left:12px;padding-right:12px}.detail-overview-grid{grid-template-columns:1fr}.usage-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.user-summary-top{display:block}.user-summary-actions{justify-content:flex-start}.user-summary-meta{grid-template-columns:1fr 1fr}}
</style>
"""


_USER_DRAWER_SCRIPT = """
<script>
(function(){
  var root=document.getElementById('wps-user-drawer-root');
  if(!root||root.dataset.bound==='true'){return;}
  root.dataset.bound='true';
  var lastTrigger=null;
  function closeDrawer(){root.hidden=true;root.innerHTML='';document.body.classList.remove('user-drawer-open');if(lastTrigger){lastTrigger.focus();}lastTrigger=null;}
  function focusDrawer(){var drawer=root.querySelector('[data-user-detail-drawer]');if(drawer){drawer.focus();}}
  async function openDrawer(trigger,url){lastTrigger=trigger;root.hidden=false;document.body.classList.add('user-drawer-open');root.innerHTML='<div class="user-drawer-overlay" data-user-drawer-overlay><aside class="user-detail-drawer" role="dialog" aria-modal="true" aria-label="WPS 用户详情" tabindex="-1"><header class="user-drawer-header"><h2>正在加载用户详情</h2><a class="user-drawer-close" href="/admin/wps/users" data-user-drawer-close aria-label="关闭用户详情">×</a></header></aside></div>';focusDrawer();try{var response=await window.fetch(url,{credentials:'same-origin',headers:{Accept:'text/html'}});if(response.redirected){window.location.assign(response.url);return;}if(!response.ok){throw new Error('DETAIL_LOAD_FAILED');}root.innerHTML=await response.text();focusDrawer();}catch(error){root.innerHTML='<div class="user-drawer-overlay" data-user-drawer-overlay><aside class="user-detail-drawer" role="dialog" aria-modal="true" aria-label="用户详情加载失败" tabindex="-1"><header class="user-drawer-header"><h2>用户详情</h2><a class="user-drawer-close" href="/admin/wps/users" data-user-drawer-close aria-label="关闭用户详情">×</a></header><p class="drawer-empty">用户详情加载失败，请刷新后重试。</p></aside></div>';focusDrawer();}}
  document.addEventListener('click',function(event){var node=event.target;if(!node||!node.closest){return;}if(node.closest('[data-user-drawer-close]')){event.preventDefault();closeDrawer();return;}var overlay=node.closest('[data-user-drawer-overlay]');if(overlay&&node===overlay){closeDrawer();return;}var link=node.closest('[data-user-drawer-url]');if(!link){return;}var url=link.getAttribute('data-user-drawer-url');if(!url){return;}event.preventDefault();openDrawer(link,url);});
  document.addEventListener('keydown',function(event){if(root.hidden){return;}if(event.key==='Escape'){event.preventDefault();closeDrawer();return;}if(event.key!=='Tab'){return;}var drawer=root.querySelector('[data-user-detail-drawer],.user-detail-drawer');if(!drawer){return;}var focusable=drawer.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])');if(!focusable.length){event.preventDefault();drawer.focus();return;}var first=focusable[0];var last=focusable[focusable.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}});
  document.addEventListener('submit',function(event){var form=event.target;if(!form||!form.matches||!form.matches('form[data-confirm]')){return;}if(!window.confirm(form.dataset.confirm||'确认执行此操作？')){event.preventDefault();}});
}());
</script>
"""


def _service_status() -> dict[str, bool]:
    """The page reached this point only after the WPS database query succeeded."""
    return {"wps_data": True}


def _status_form(
    *,
    resource: str,
    resource_id: object,
    current_status: object,
    csrf_input: str,
) -> str:
    """Render a small POST-only toggle using the server-owned mutation endpoint."""
    target = "disabled" if str(current_status) == "active" else "active"
    label = "停用" if target == "disabled" else "恢复"
    subject = "账号" if resource == "users" else "设备"
    confirmation = (
        f"确认停用该{subject}并撤销其当前公网会话？"
        if target == "disabled"
        else f"确认恢复该{subject}？"
    )
    return (
        f'<form class="inline-form" method="post" action="/admin/wps/{resource}/{_escape(resource_id)}/status" data-confirm="{confirmation}">'
        f'{csrf_input}<input type="hidden" name="status" value="{target}">'
        f'<button class="button{" danger" if target == "disabled" else ""}" type="submit">{label}</button></form>'
    )


def _audit_event_label(value: object) -> str:
    """Present persisted audit event names without hiding the stable event identity."""
    labels = {
        "wps.admin.user.status.updated": "账号状态已更新",
        "wps.admin.device.status.updated": "设备状态已更新",
        "wps.admin.user.password_reset": "密码已重置",
        "wps.admin.notification.sent": "通知已发送",
        "wps.admin.user.deleted": "账号已彻底删除",
        "wps.admin.user.delete.denied": "账号删除被拒绝",
    }
    raw = str(value or "")
    return labels.get(raw, raw or "-")


def render_wps_overview_page(
    *,
    summary: Mapping[str, object],
    trend: list[Mapping[str, object]],
    recent: list[Mapping[str, object]],
    csrf_input: str,
) -> str:
    """Render the WPS operation overview using only queried WPS database data."""
    completed = int(summary.get("success", 0) or 0) + int(summary.get("failed", 0) or 0)
    success_rate = "-" if not completed else f"{int(summary.get('success', 0) or 0) / completed * 100:.1f}%"
    recent_rows = []
    for row in recent:
        label, class_name = _status(row.get("status"))
        recent_rows.append(
            f'<tr><td>{_time(row.get("requested_at"))}</td><td>{_escape(row.get("username", "-"))}</td><td>{_escape(row.get("device_name", "-"))}</td><td>{_escape(row.get("command", "-"))}</td><td><span class="status-tag {class_name}">{label}</span></td><td>{int(row.get("duration_ms", 0) or 0)} ms</td></tr>'
        )
    trend_rows = "".join(
        f'<tr><td>{_escape(row.get("date", "-"))}</td><td>{int(row.get("total", 0) or 0)}</td><td class="ok">{int(row.get("success", 0) or 0)}</td><td class="bad">{int(row.get("failed", 0) or 0)}</td></tr>'
        for row in trend
    )
    body = f"""<div class="metric-grid"><div class="metric"><b>{int(summary.get('users', 0) or 0)}</b><span>账号</span></div><div class="metric"><b>{int(summary.get('online_devices', 0) or 0)}</b><span>在线设备</span></div><div class="metric"><b>{int(summary.get('requests', 0) or 0)}</b><span>排版请求</span></div><div class="metric"><b>{success_rate}</b><span>成功率</span></div><div class="metric good"><b>{int(summary.get('success', 0) or 0)}</b><span>成功</span></div><div class="metric bad"><b>{int(summary.get('failed', 0) or 0)}</b><span>失败</span></div><div class="metric"><b>{int(summary.get('pending', 0) or 0)}</b><span>待回报</span></div><div class="metric"><b>{int(summary.get('average_duration_ms', 0) or 0)} ms</b><span>平均耗时</span></div></div>
<section class="panel"><div class="panel-head"><div><h2>最近排版请求</h2><p>展示真实存在的最近 WPS 授权、成功、失败或待回报请求</p></div><a class="button" href="/admin/wps/tasks">查看全部</a></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>账号</th><th>设备</th><th>命令</th><th>状态</th><th>耗时</th></tr></thead><tbody>{''.join(recent_rows) or '<tr><td colspan="6"><div class="empty">暂无排版请求</div></td></tr>'}</tbody></table></div></section>
<section class="panel"><div class="panel-head"><div><h2>近 7 天趋势</h2><p>没有请求的日期不会伪造为零值记录</p></div></div><div class="table-wrap"><table><thead><tr><th>日期</th><th>请求</th><th>成功</th><th>失败</th></tr></thead><tbody>{trend_rows or '<tr><td colspan="4"><div class="empty">暂无趋势数据</div></td></tr>'}</tbody></table></div></section>"""
    return render_admin_shell(title="WPS 运行总览", active_module="wps", active_page="overview", body=body, csrf_input=csrf_input, service_status=_service_status())


def render_wps_users_page(
    *,
    result: Mapping[str, object],
    filters: Mapping[str, object],
    csrf_input: str,
    mutations_enabled: bool = False,
) -> str:
    """Render the paged WPS user list with a progressive user-detail drawer."""
    rows = []
    for row in result.get("rows", []):
        label, class_name = _status(row.get("status"))
        detail_url = _user_url(row.get("id"))
        drawer_url = _user_url(row.get("id"), drawer=True)
        rows.append(
            f'<tr><td>{_escape(row.get("username"))}</td><td><span class="status-tag {class_name}">{label}</span></td><td>{_time(row.get("created_at"))}</td><td>{_time(row.get("last_login_at"))}</td><td>{int(row.get("device_count", 0) or 0)}</td><td>{"在线" if row.get("online") else "离线"}</td><td>{int(row.get("format_total", 0) or 0)}</td><td class="ok">{int(row.get("format_success", 0) or 0)}</td><td class="bad">{int(row.get("format_failed", 0) or 0)}</td><td>{int(row.get("format_pending", 0) or 0)}</td><td>{_escape(row.get("app_version", "-") or "-")}</td><td><a class="user-detail-link" href="{_escape(detail_url)}" data-user-drawer-url="{_escape(drawer_url)}">详情</a></td></tr>'
        )
    body = f"""{_USER_DETAIL_STYLE}<section class="panel"><div class="panel-head"><div><h2>用户管理</h2><p>按服务端分页查询账号、设备和排版统计；点击详情在当前列表右侧打开用户详情。</p></div>{_filters('/admin/wps/users', filters, online=True, version=True, placeholder='搜索登录账号')}</div><div class="table-wrap"><table><thead><tr><th>登录账号</th><th>状态</th><th>注册时间</th><th>最后登录</th><th>设备</th><th>在线</th><th>排版</th><th>成功</th><th>失败</th><th>待回报</th><th>版本</th><th>操作</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="12"><div class="empty">暂无 WPS 用户</div></td></tr>'}</tbody></table></div>{_pager('/admin/wps/users', result, filters)}</section><div id="wps-user-drawer-root" hidden></div>{_USER_DRAWER_SCRIPT}"""
    return render_admin_shell(title="WPS 用户管理", active_module="wps", active_page="users", body=body, csrf_input=csrf_input, service_status=_service_status())


def render_wps_devices_page(
    *,
    result: Mapping[str, object],
    filters: Mapping[str, object],
    csrf_input: str,
    mutations_enabled: bool = False,
) -> str:
    """Render the paged device list and gate-controlled status actions."""
    rows = []
    for row in result.get("rows", []):
        label, class_name = _status(row.get("status"))
        action = (
            _status_form(
                resource="devices",
                resource_id=row.get("id"),
                current_status=row.get("status"),
                csrf_input=csrf_input,
            )
            if mutations_enabled
            else ""
        )
        rows.append(
            f'<tr><td>{_escape(row.get("username", "-"))}</td><td>{_escape(row.get("device_name", "-"))}</td><td>{_escape(row.get("platform", "-"))}</td><td>{_escape(row.get("app_version", "-"))}</td><td><span class="status-tag {class_name}">{label}</span></td><td>{"在线" if row.get("online") else "离线"}</td><td>{_time(row.get("last_seen_at"))}</td><td>{int(row.get("format_total", 0) or 0)}</td><td><a class="ok" href="/admin/wps/users/{_escape(row.get("user_id"))}?tab=devices">详情</a>{action}</td></tr>'
        )
    action_label = "详情与操作" if mutations_enabled else "详情"
    body = f"""<section class="panel"><div class="panel-head"><div><h2>设备管理</h2><p>按设备名称、账号、状态、在线状态和版本查询；写操作由服务端门禁统一控制。</p></div>{_filters('/admin/wps/devices', filters, online=True, version=True)}</div><div class="table-wrap"><table><thead><tr><th>账号</th><th>设备名称</th><th>平台</th><th>版本</th><th>状态</th><th>在线</th><th>最后在线</th><th>排版</th><th>{action_label}</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="9"><div class="empty">暂无 WPS 设备</div></td></tr>'}</tbody></table></div>{_pager('/admin/wps/devices', result, filters)}</section>"""
    return render_admin_shell(title="WPS 设备管理", active_module="wps", active_page="devices", body=body, csrf_input=csrf_input, service_status=_service_status())


def render_wps_tasks_page(*, result: Mapping[str, object], filters: Mapping[str, object], csrf_input: str) -> str:
    """Render the paged WPS formatting request list."""
    rows = []
    for row in result.get("rows", []):
        label, class_name = _status(row.get("status"))
        rows.append(
            f'<tr><td>{_time(row.get("requested_at"))}</td><td>{_escape(row.get("request_id", "-"))}</td><td>{_escape(row.get("document_name", "-") or "-")}</td><td>{_escape(row.get("username", "-"))}</td><td>{_escape(row.get("device_name", "-"))}</td><td>{_escape(row.get("command", "-"))}</td><td><span class="status-tag {class_name}">{label}</span></td><td>{int(row.get("duration_ms", 0) or 0)} ms</td><td>{_escape(row.get("error_code", "-") or "-")}</td><td>{_escape(row.get("app_version", "-") or "-")}</td></tr>'
        )
    body = f"""<section class="panel"><div class="panel-head"><div><h2>WPS 排版任务</h2><p>服务端分页显示授权、成功、失败和待回报请求</p></div>{_filters('/admin/wps/tasks', filters, version=True, request_status=True)}</div><div class="table-wrap"><table><thead><tr><th>请求时间</th><th>请求编号</th><th>文件名</th><th>账号</th><th>设备</th><th>命令</th><th>状态</th><th>耗时</th><th>错误码</th><th>版本</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="10"><div class="empty">暂无 WPS 排版请求</div></td></tr>'}</tbody></table></div>{_pager('/admin/wps/tasks', result, filters)}</section>"""
    return render_admin_shell(title="WPS 排版任务", active_module="wps", active_page="tasks", body=body, csrf_input=csrf_input, service_status=_service_status())


def _user_overview(detail: Mapping[str, object]) -> str:
    """Render the reference overview with only fields that the WPS database owns."""
    user = dict(detail.get("user") or {})
    summary = dict(detail.get("summary") or {})
    device = dict(detail.get("current_device") or {})
    status_label, status_class = _status(user.get("status"))
    device_label, device_class = _status(device.get("status")) if device else ("-", "info")
    online = int(summary.get("online_devices", 0) or 0) > 0
    online_label = "在线" if online else "离线"
    online_class = "ok" if online else "bad"
    device_name = _escape(device.get("device_name") or "暂无设备")
    platform = _escape(device.get("platform") or "-")
    version = _escape(device.get("app_version") or "-")
    return f"""<div class="user-overview"><div class="detail-overview-grid">
<section class="detail-card"><h3>账号状态</h3><strong class="{'ok' if status_class == 'good' else 'bad' if status_class == 'bad' else ''}">{status_label}</strong><p class="hint">账号当前状态</p><div class="detail-facts"><div><span>在线状态</span><b class="{online_class}">{online_label}</b></div><div><span>在线设备</span><b>{int(summary.get('online_devices', 0) or 0)}</b></div><div><span>设备数量</span><b>{int(summary.get('device_count', 0) or 0)}</b></div></div></section>
<section class="detail-card"><h3>当前设备</h3><strong>{device_name}</strong><p class="hint">{platform}</p><div class="detail-facts"><div><span>连接状态</span><b class="{'ok' if device.get('online') else 'bad' if device else ''}">{'在线' if device.get('online') else '离线' if device else '-'}</b></div><div><span>设备状态</span><b class="{'ok' if device_class == 'good' else 'bad' if device_class == 'bad' else ''}">{device_label}</b></div><div><span>最后在线</span><b>{_time(device.get('last_seen_at'))}</b></div></div></section>
<section class="detail-card"><h3>插件信息</h3><strong>{version}</strong><p class="hint">当前设备上报的插件版本</p><div class="detail-facts"><div><span>插件版本</span><b>{version}</b></div><div><span>平台</span><b>{platform}</b></div><div><span>最后心跳</span><b>{_time(device.get('last_seen_at'))}</b></div></div></section>
</div><section class="usage-section"><h3>使用统计</h3><div class="usage-grid"><div class="usage-metric"><b>{int(summary.get('format_total', 0) or 0)}</b><span>总排版任务</span></div><div class="usage-metric good"><b>{int(summary.get('format_success', 0) or 0)}</b><span>成功任务</span></div><div class="usage-metric bad"><b>{int(summary.get('format_failed', 0) or 0)}</b><span>失败任务</span></div><div class="usage-metric"><b>{int(summary.get('format_pending', 0) or 0)}</b><span>待回报任务</span></div><div class="usage-metric"><b>{_duration(summary.get('average_duration_ms'))}</b><span>平均耗时</span></div><div class="usage-metric"><b>{int(summary.get('online_devices', 0) or 0)}</b><span>在线设备</span></div></div></section></div>"""


def _user_drawer_summary(detail: Mapping[str, object], *, mutations_enabled: bool) -> str:
    """Render the drawer header from persisted identity and status facts only."""
    user = dict(detail.get("user") or {})
    device = dict(detail.get("current_device") or {})
    user_id = user.get("id")
    status_label, status_class = _status(user.get("status"))
    username = str(user.get("username") or "-")
    metadata = [
        ("登录账号", username),
        ("用户 ID", str(user_id or "-")),
        ("注册时间", _time(user.get("created_at"))),
        ("最后登录", _time(user.get("last_login_at"))),
    ]
    if device:
        metadata.append(("最后在线", _time(device.get("last_seen_at"))))
    meta_html = "".join(
        f'<div><span>{_escape(label)}</span><b>{_escape(value)}</b></div>'
        for label, value in metadata
    )
    actions = [_drawer_link(user_id, "查看设备", tab="devices"), _drawer_link(user_id, "查看日志", tab="logs")]
    if mutations_enabled:
        actions.extend(
            (
                _drawer_link(user_id, "停用账号" if user.get("status") == "active" else "恢复账号", tab="security", danger=user.get("status") == "active"),
                _drawer_link(user_id, "重置密码", tab="security"),
                _drawer_link(user_id, "发送通知", tab="security"),
                _drawer_link(user_id, "删除账号", tab="security", danger=True),
            )
        )
    return f"""<section class="user-summary"><div class="user-summary-top"><div class="user-identity"><div class="user-avatar" aria-hidden="true">{_escape(username[:1].upper() or '?')}</div><div><h3>{_escape(username)}</h3><span class="status-tag {status_class}">{status_label}</span></div></div></div><div class="user-summary-meta">{meta_html}</div><div class="user-summary-actions">{''.join(actions)}</div></section>"""


def _render_user_drawer(
    *,
    detail: Mapping[str, object],
    tab_links: str,
    content: str,
    mutations_enabled: bool,
) -> str:
    """Return the same detail data as a right-side dialog fragment for the user list."""
    return f"""{_USER_DETAIL_STYLE}<div class="user-drawer-overlay" data-user-drawer-overlay><aside class="user-detail-drawer" data-user-detail-drawer role="dialog" aria-modal="true" aria-labelledby="user-detail-title" tabindex="-1"><header class="user-drawer-header"><h2 id="user-detail-title">WPS 用户详情</h2><a class="user-drawer-close" href="/admin/wps/users" data-user-drawer-close aria-label="关闭用户详情">×</a></header><div class="user-drawer-scroll">{_user_drawer_summary(detail, mutations_enabled=mutations_enabled)}<nav class="drawer-tabs" aria-label="用户详情标签">{tab_links}</nav><div class="drawer-content">{content}</div></div></aside></div>"""


def render_wps_user_page(
    *,
    detail: Mapping[str, object],
    tab: str,
    result: Mapping[str, object] | None,
    filters: Mapping[str, object],
    csrf_input: str,
    audit_result: Mapping[str, object] | None = None,
    mutations_enabled: bool = False,
    drawer: bool = False,
) -> str:
    """Render a user page normally or as a progressively loaded detail drawer."""
    user = dict(detail["user"])
    user_id = user.get("id")
    if tab == "devices":
        content = _user_devices_tab(
            str(user_id or ""),
            result or {},
            filters,
            csrf_input=csrf_input,
            mutations_enabled=mutations_enabled,
        )
    elif tab == "tasks":
        content = _user_tasks_tab(str(user_id or ""), result or {}, filters)
    elif tab == "logs":
        content = _user_audit_logs_tab(str(user_id or ""), audit_result or {}, filters)
    elif tab == "security":
        content = _user_security_tab(user, csrf_input=csrf_input, mutations_enabled=mutations_enabled)
    else:
        content = _user_overview(detail)
    if drawer:
        return _render_user_drawer(
            detail=detail,
            tab_links=_user_tabs(user_id, tab, drawer=True),
            content=content,
            mutations_enabled=mutations_enabled,
        )
    body = f"""{_USER_DETAIL_STYLE}<section class="panel"><div class="panel-head"><div><h2>{_escape(user.get('username'))}</h2><p>用户详情只展示当前数据库实际存在的字段。</p></div><a class="button" href="/admin/wps/users">返回用户管理</a></div><div class="tabs">{_user_tabs(user_id, tab, drawer=False)}</div><div class="panel-body">{content}</div></section>"""
    return render_admin_shell(title="WPS 用户详情", active_module="wps", active_page="users", body=body, csrf_input=csrf_input, service_status=_service_status())


def _user_devices_tab(
    user_id: str,
    result: Mapping[str, object],
    filters: Mapping[str, object],
    *,
    csrf_input: str,
    mutations_enabled: bool,
) -> str:
    rows = []
    for row in result.get("rows", []):
        label, class_name = _status(row.get("status"))
        action = (
            _status_form(
                resource="devices",
                resource_id=row.get("id"),
                current_status=row.get("status"),
                csrf_input=csrf_input,
            )
            if mutations_enabled
            else ""
        )
        rows.append(
            f'<tr><td>{_escape(row.get("device_name", "-"))}</td><td>{_escape(row.get("platform", "-"))}</td><td>{_escape(row.get("app_version", "-"))}</td><td><span class="status-tag {class_name}">{label}</span></td><td>{"在线" if row.get("online") else "离线"}</td><td>{_time(row.get("last_seen_at"))}</td><td>{action or "-"}</td></tr>'
        )
    filters = {**filters, "q": "", "status": "", "online": "", "version": ""}
    path = _user_url(user_id)
    empty = '<tr><td colspan="7"><div class="empty">暂无设备</div></td></tr>'
    pager = _pager(path, result, {**filters, "tab": "devices"})
    return f'<div class="table-wrap"><table><thead><tr><th>设备</th><th>平台</th><th>版本</th><th>状态</th><th>在线</th><th>最后在线</th><th>操作</th></tr></thead><tbody>{"".join(rows) or empty}</tbody></table></div>{pager}'


def _user_tasks_tab(user_id: str, result: Mapping[str, object], filters: Mapping[str, object]) -> str:
    rows = "".join(
        f'<tr><td>{_time(row.get("requested_at"))}</td><td>{_escape(row.get("request_id", "-"))}</td><td>{_escape(row.get("command", "-"))}</td><td>{_escape(row.get("status", "-"))}</td><td>{int(row.get("duration_ms", 0) or 0)} ms</td><td>{_escape(row.get("error_code", "-") or "-")}</td></tr>'
        for row in result.get("rows", [])
    )
    filters = {**filters, "q": "", "status": "", "online": "", "version": ""}
    path = _user_url(user_id)
    empty = '<tr><td colspan="6"><div class="empty">暂无排版请求</div></td></tr>'
    pager = _pager(path, result, {**filters, "tab": "tasks"})
    return f'<div class="table-wrap"><table><thead><tr><th>请求时间</th><th>请求编号</th><th>命令</th><th>状态</th><th>耗时</th><th>错误码</th></tr></thead><tbody>{rows or empty}</tbody></table></div>{pager}'


def _user_audit_logs_tab(
    user_id: str,
    result: Mapping[str, object],
    filters: Mapping[str, object],
) -> str:
    """Render only persisted, non-sensitive administrator audit entries."""
    rows = []
    for row in result.get("rows", []):
        result_label, result_class = _status(row.get("result"))
        rows.append(
            f'<tr><td>{_time(row.get("created_at"))}</td><td>{_escape(_audit_event_label(row.get("event")))}</td><td><span class="status-tag {result_class}">{_escape(result_label)}</span></td><td>{_escape(row.get("error_code", "-") or "-")}</td><td>{_escape(row.get("actor_type", "-") or "-")}</td></tr>'
        )
    filters = {**filters, "q": "", "status": "", "online": "", "version": ""}
    pager = _pager(
        _user_url(user_id),
        result,
        {**filters, "tab": "logs"},
    )
    empty = '<tr><td colspan="5"><div class="empty">暂无管理员审计记录</div></td></tr>'
    return f'<div class="panel-body"><p class="hint">这里只显示数据库中真实存在的管理员审计事实，不显示密码、会话令牌或完整请求内容。</p></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>事件</th><th>结果</th><th>错误码</th><th>授权上下文</th></tr></thead><tbody>{"".join(rows) or empty}</tbody></table></div>{pager}'


def _user_security_tab(
    user: Mapping[str, object],
    *,
    csrf_input: str,
    mutations_enabled: bool,
) -> str:
    """Render destructive controls only when the process-startup server gate is enabled."""
    user_id = _escape(user.get("id"))
    username = _escape(user.get("username"))
    if not mutations_enabled:
        return '<div class="panel-body"><p class="hint">WPS 管理写操作尚未启用。服务端门禁关闭时，页面不会显示状态变更、密码重置、通知或账号删除；直接 POST 也会被拒绝。</p></div>'
    status_form = _status_form(
        resource="users",
        resource_id=user.get("id"),
        current_status=user.get("status"),
        csrf_input=csrf_input,
    )
    return f'''<div class="panel-body mutation-stack">
<section class="mutation-card"><h3>账号状态</h3><p class="hint">停用账号会立即撤销该账号全部公网会话；用户需在账号恢复后重新登录。本机待补报结果不会被服务端操作删除。</p>{status_form}</section>
<section class="mutation-card"><h3>重置密码</h3><p class="hint">密码重置会撤销该账号全部公网会话，明文密码不会写入日志或审计记录。</p><form class="mutation-form" method="post" action="/admin/wps/users/{user_id}/password">{csrf_input}<label>新密码<input type="password" name="password" autocomplete="new-password" required></label><label>确认新密码<input type="password" name="password_confirmation" autocomplete="new-password" required></label><button class="button primary" type="submit">重置密码</button></form></section>
<section class="mutation-card"><h3>发送通知</h3><p class="hint">通知按账号送达，任务窗格只按纯文本展示。标题、正文和级别会在服务端校验，审计只记录发送事实，不记录正文。</p><form class="mutation-form notification-form" method="post" action="/admin/wps/users/{user_id}/notifications">{csrf_input}<label>标题<input type="text" name="title" maxlength="120" autocomplete="off" required></label><label>级别<select name="level"><option value="info">提示</option><option value="warning">注意</option><option value="error">重要</option></select></label><label class="notification-body">正文<textarea name="body" maxlength="2000" rows="5" required></textarea></label><button class="button primary" type="submit">发送通知</button></form></section>
<section class="mutation-card danger-card"><h3>彻底删除账号</h3><p class="hint">将永久删除账号 {username} 的设备、会话、排版请求和待确认通知，历史统计会随之变化，且无法由本页面恢复。管理员审计事实会保留。</p><form class="mutation-form" method="post" action="/admin/wps/users/{user_id}/delete">{csrf_input}<label>输入当前账号名确认<input type="text" name="confirmation_username" autocomplete="off" required></label><button class="button danger" type="submit">彻底删除账号</button></form></section>
</div>'''
