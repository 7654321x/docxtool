"""Unified administrator workspace pages for Web and WPS business data."""

from __future__ import annotations

import html
from datetime import datetime


def _time(value) -> str:
    if not value:
        return "-"
    return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M")


def render_admin_shell(*, title: str, active: str, body: str, csrf_input: str) -> str:
    links = [
        ("home", "/admin", "综合概览"),
        ("web", "/admin/web", "网页业务"),
        ("wps", "/admin/wps/users", "WPS 插件"),
    ]
    nav = "".join(
        f'<a class="{"active" if key == active else ""}" href="{url}">{label}</a>'
        for key, url, label in links
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · DocxTool</title>
<style>:root{{--bg:#07101f;--panel:#0d1a2e;--line:rgba(160,181,215,.17);--muted:#8fa2be;--text:#edf4ff;--gold:#f6c85f;--green:#55d6a0;--red:#fb7185}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px "Microsoft YaHei",sans-serif}}a{{color:inherit;text-decoration:none}}.shell{{display:grid;grid-template-columns:220px minmax(0,1fr);min-height:100vh}}aside{{padding:24px 16px;border-right:1px solid var(--line)}}.brand{{display:block;font-size:18px;font-weight:800;margin:0 8px 28px}}nav{{display:grid;gap:6px}}nav a{{padding:11px 12px;border-radius:7px;color:#b8c8df}}nav a.active,nav a:hover{{background:rgba(246,200,95,.12);color:#ffe7a4}}main{{padding:28px 32px}}header{{display:flex;justify-content:space-between;gap:16px;align-items:center;border-bottom:1px solid var(--line);padding-bottom:18px}}h1{{font-size:24px;margin:0}}.actions{{display:flex;gap:8px;align-items:center}}button,.button,input,select{{font:inherit}}button,.button{{border:1px solid var(--line);border-radius:6px;background:#12233b;color:#dce8fa;padding:8px 11px;cursor:pointer}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:12px;margin-top:22px}}.card,.panel{{border:1px solid var(--line);background:var(--panel);border-radius:8px}}.card{{padding:18px}}.card b{{display:block;color:var(--gold);font-size:26px}}.card span,.muted{{color:var(--muted);font-size:12px}}.panel{{margin-top:20px;overflow:hidden}}.panel-head{{padding:15px 17px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}}.panel-body{{padding:17px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;text-align:left;border-top:1px solid rgba(160,181,215,.1);white-space:nowrap}}th{{color:var(--muted);font-size:11px}}.ok{{color:var(--green)}}.bad{{color:var(--red)}}.search{{display:flex;gap:8px;flex-wrap:wrap}}input,select{{border:1px solid var(--line);background:#081529;color:var(--text);padding:8px;border-radius:6px}}form{{margin:0}}@media(max-width:800px){{.shell{{display:block}}aside{{border-right:0;border-bottom:1px solid var(--line)}}nav{{display:flex}}main{{padding:20px}}.grid{{grid-template-columns:repeat(2,1fr)}}.panel{{overflow-x:auto}}}}</style></head><body><div class="shell"><aside><a class="brand" href="/admin">DocxTool 管理工作台</a><nav>{nav}</nav></aside><main><header><h1>{html.escape(title)}</h1><div class="actions"><a class="button" href="/">返回工具</a><form method="post" action="/admin/logout">{csrf_input}<button type="submit">退出</button></form></div></header>{body}</main></div></body></html>"""


def render_admin_home_page(*, web_summary: dict, wps_summary: dict, readiness: dict, csrf_input: str) -> str:
    body = f"""<div class="grid"><div class="card"><b>{web_summary.get('total',0)}</b><span>网页任务总数</span></div><div class="card"><b>{web_summary.get('done',0)}</b><span>网页成功任务</span></div><div class="card"><b>{web_summary.get('error',0)}</b><span>网页失败任务</span></div><div class="card"><b>{web_summary.get('queued',0)}</b><span>网页当前排队</span></div><div class="card"><b>{wps_summary.get('users',0)}</b><span>WPS 用户数</span></div><div class="card"><b>{wps_summary.get('online_devices',0)}</b><span>WPS 在线设备</span></div><div class="card"><b>{wps_summary.get('requests',0)}</b><span>WPS 排版请求总数</span></div><div class="card"><b>{wps_summary.get('pending',0)}</b><span>WPS 待回报数</span></div></div><div class="panel"><div class="panel-head"><strong>服务状态</strong><span class="{'ok' if readiness.get('ok') else 'bad'}">{'正常' if readiness.get('ok') else '需检查'}</span></div><div class="panel-body muted">网页业务库与 WPS 插件库独立运行。</div></div>"""
    return render_admin_shell(title="综合概览", active="home", body=body, csrf_input=csrf_input)


def render_wps_users_page(*, rows: list[dict], query: str, status: str, csrf_input: str) -> str:
    table_rows = "".join(
        f"<tr><td><a href=\"/admin/wps/users/{html.escape(row['id'])}\">{html.escape(row['username'])}</a></td><td class=\"{'ok' if row['status']=='active' else 'bad'}\">{'正常' if row['status']=='active' else '停用'}</td><td>{_time(row['created_at'])}</td><td>{_time(row['last_login_at'])}</td><td>{row['device_count']}</td><td>{'在线' if row['online'] else '离线'}</td><td>{row['format_total']}</td><td>{row['format_success'] or 0}</td><td>{row['format_failed'] or 0}</td><td>{row['format_pending'] or 0}</td><td>{_time(row['last_format_at'])}</td><td>{html.escape(row['app_version'] or '-')}</td></tr>"
        for row in rows
    ) or '<tr><td colspan="12" class="muted">暂无 WPS 用户</td></tr>'
    body = f"""<div class="panel"><div class="panel-head"><form class="search" method="get" action="/admin/wps/users"><input name="q" value="{html.escape(query)}" placeholder="搜索登录账号"><select name="status"><option value="">全部状态</option><option value="active" {'selected' if status=='active' else ''}>正常</option><option value="disabled" {'selected' if status=='disabled' else ''}>停用</option></select><button type="submit">查询</button></form><span class="muted">共 {len(rows)} 条</span></div><table><thead><tr><th>登录账号</th><th>状态</th><th>注册时间</th><th>最后登录</th><th>设备</th><th>在线</th><th>排版</th><th>成功</th><th>失败</th><th>待回报</th><th>最后排版</th><th>版本</th></tr></thead><tbody>{table_rows}</tbody></table></div>"""
    return render_admin_shell(title="WPS 用户", active="wps", body=body, csrf_input=csrf_input)


def render_wps_user_page(*, detail: dict, csrf_input: str) -> str:
    user = detail["user"]
    target_status = "disabled" if user["status"] == "active" else "active"
    devices = "".join(
        f"<tr><td>{html.escape(row['device_name'])}</td><td>{html.escape(row['platform'])}</td><td>{html.escape(row['app_version'])}</td><td>{'正常' if row['status']=='active' else '停用'}</td><td>{_time(row['last_seen_at'])}</td><td><form method=\"post\" action=\"/admin/wps/devices/{html.escape(row['id'])}/status\">{csrf_input}<input type=\"hidden\" name=\"status\" value=\"{'disabled' if row['status']=='active' else 'active'}\"><input type=\"hidden\" name=\"user_id\" value=\"{html.escape(user['id'])}\"><button type=\"submit\">{'停用' if row['status']=='active' else '恢复'}</button></form></td></tr>"
        for row in detail["devices"]
    ) or '<tr><td colspan="6">暂无设备</td></tr>'
    requests = "".join(
        f"<tr><td>{html.escape(row['request_id'])}</td><td>{html.escape(row['command'])}</td><td>{html.escape(row['status'])}</td><td>{html.escape(row['config_version'])}</td><td>{_time(row['requested_at'])}</td><td>{row['duration_ms']}</td><td>{html.escape(row['error_code'])}</td></tr>"
        for row in detail["requests"]
    ) or '<tr><td colspan="7">暂无排版请求</td></tr>'
    body = f"""<div class="panel"><div class="panel-head"><div><strong>{html.escape(user['username'])}</strong><div class="muted">注册于 {_time(user['created_at'])}</div></div><form method="post" action="/admin/wps/users/{html.escape(user['id'])}/status">{csrf_input}<input type="hidden" name="status" value="{target_status}"><button type="submit">{'停用账号' if target_status=='disabled' else '恢复账号'}</button></form></div></div><div class="panel"><div class="panel-head"><strong>设备</strong></div><table><thead><tr><th>名称</th><th>平台</th><th>版本</th><th>状态</th><th>最后在线</th><th>操作</th></tr></thead><tbody>{devices}</tbody></table></div><div class="panel"><div class="panel-head"><strong>最近排版请求</strong></div><table><thead><tr><th>请求编号</th><th>功能</th><th>状态</th><th>配置</th><th>时间</th><th>耗时</th><th>错误</th></tr></thead><tbody>{requests}</tbody></table></div>"""
    return render_admin_shell(title="WPS 用户详情", active="wps", body=body, csrf_input=csrf_input)
