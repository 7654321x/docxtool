"""Shared server-rendered shell and navigation for the administrator workspace."""

from __future__ import annotations

import html
from collections.abc import Mapping


ADMIN_NAVIGATION = (
    {
        "key": "home",
        "label": "综合概览",
        "href": "/admin",
        "children": (),
    },
    {
        "key": "web",
        "label": "网页业务",
        "href": "/admin/web/tasks",
        "children": (
            ("tasks", "任务中心", "/admin/web/tasks"),
            ("security", "安全与访问", "/admin/web/security"),
            ("runtime", "运行设置", "/admin/web/runtime"),
            ("logs", "日志查询", "/admin/web/logs"),
        ),
    },
    {
        "key": "wps",
        "label": "WPS 插件",
        "href": "/admin/wps",
        "children": (
            ("overview", "运行总览", "/admin/wps"),
            ("users", "用户管理", "/admin/wps/users"),
            ("devices", "设备管理", "/admin/wps/devices"),
            ("tasks", "排版任务", "/admin/wps/tasks"),
        ),
    },
)


def _navigation_html(active_module: str, active_page: str) -> str:
    """Render the canonical primary navigation with both module submenus visible."""
    rendered: list[str] = []
    for item in ADMIN_NAVIGATION:
        key = item["key"]
        active = key == active_module
        rendered.append(
            f'<a class="primary-nav{" active" if active else ""}" '
            f'href="{html.escape(str(item["href"]), quote=True)}">'
            f'{html.escape(str(item["label"]))}</a>'
        )
        children = item["children"]
        if not children:
            continue
        child_html = "".join(
            f'<a class="secondary-nav{" active" if active and child_key == active_page else ""}" '
            f'href="{html.escape(child_href, quote=True)}">{html.escape(child_label)}</a>'
            for child_key, child_label, child_href in children
        )
        rendered.append(f'<nav class="secondary-nav-list" aria-label="{html.escape(str(item["label"]))}子菜单">{child_html}</nav>')
    return "".join(rendered)


def _status_html(service_status: Mapping[str, object] | None) -> str:
    """Render only actual, caller-provided service status summaries."""
    values = dict(service_status or {})
    labels = (
        ("web", "网页服务", "就绪"),
        ("wps_data", "WPS 数据库", "可读"),
    )
    pills = []
    for key, label, success_state in labels:
        if key not in values:
            continue
        available = bool(values[key])
        state = success_state if available else "需检查"
        pills.append(
            f'<span class="service-state{" ready" if available else " problem"}">'
            f'<i></i>{label}{state}</span>'
        )
    return "".join(pills)


def render_admin_shell(
    *,
    title: str,
    active_module: str,
    active_page: str = "",
    body: str,
    csrf_input: str,
    service_status: Mapping[str, object] | None = None,
) -> str:
    """Render the common administrator chrome around trusted page body markup."""
    navigation = _navigation_html(active_module, active_page)
    status = _status_html(service_status)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · DocxTool</title>
<style>
:root{{--bg:#07101f;--panel:#0d1a2e;--panel-raised:#12233b;--line:rgba(160,181,215,.17);--muted:#8fa2be;--text:#edf4ff;--gold:#f6c85f;--gold-soft:rgba(246,200,95,.12);--green:#55d6a0;--red:#fb7185;--blue:#9bc8ff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px "Microsoft YaHei","Noto Sans CJK SC",Arial,sans-serif}}a{{color:inherit;text-decoration:none}}button,input,select{{font:inherit}}button{{cursor:pointer}}
.workspace{{display:grid;grid-template-columns:224px minmax(0,1fr);min-height:100vh}}.sidebar{{padding:24px 16px;border-right:1px solid var(--line);background:linear-gradient(180deg,#0b1729,#07101f)}}.brand{{display:block;padding:0 8px 24px;border-bottom:1px solid var(--line);font-size:17px;font-weight:800}}.brand small{{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:4px}}
.primary-nav-list{{display:grid;gap:5px;margin-top:20px}}.primary-nav,.secondary-nav{{display:block;border:1px solid transparent;color:#b8c8df;border-radius:9px;transition:.15s}}.primary-nav{{padding:11px 12px;font-weight:650}}.primary-nav:hover,.primary-nav.active{{background:var(--gold-soft);border-color:rgba(246,200,95,.2);color:#ffe7a4}}.secondary-nav-list{{display:grid;gap:2px;margin:3px 0 8px 14px;padding-left:10px;border-left:1px solid rgba(160,181,215,.18)}}.secondary-nav{{padding:7px 9px;font-size:12px}}.secondary-nav:hover,.secondary-nav.active{{color:#ffe7a4;background:rgba(246,200,95,.08)}}
.main{{min-width:0;padding:22px 30px 40px}}.topbar{{display:flex;align-items:center;justify-content:space-between;gap:18px;padding-bottom:18px;border-bottom:1px solid var(--line)}}.title-kicker{{color:var(--gold);font-size:10px;letter-spacing:.1em;margin-bottom:5px}}h1{{margin:0;font-size:25px;letter-spacing:.01em}}.top-actions{{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}}.service-state{{display:inline-flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid rgba(85,214,160,.25);border-radius:999px;background:rgba(85,214,160,.08);color:#a7f3d0;font-size:11px}}.service-state i{{width:6px;height:6px;border-radius:50%;background:var(--green)}}.service-state.problem{{border-color:rgba(251,113,133,.3);background:rgba(251,113,133,.08);color:#fecdd3}}.service-state.problem i{{background:var(--red)}}
.button{{display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:0 11px;border:1px solid var(--line);border-radius:7px;background:rgba(255,255,255,.04);color:#c8d6e9;font-size:12px}}.button:hover{{border-color:rgba(246,200,95,.42);color:#ffe7a4}}.button.primary{{border-color:rgba(246,200,95,.35);background:var(--gold-soft);color:#ffe7a4}}form{{margin:0}}
.metric-grid{{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:10px;margin-top:20px}}.metric{{min-width:0;padding:15px;border:1px solid var(--line);border-radius:10px;background:linear-gradient(145deg,rgba(18,35,59,.92),rgba(10,24,42,.92))}}.metric b{{display:block;color:#f6d985;font-size:24px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.metric.good b{{color:var(--green)}}.metric.bad b{{color:#ff9cab}}.metric span{{display:block;color:var(--muted);font-size:11px;margin-top:6px}}
.panel{{min-width:0;margin-top:18px;border:1px solid var(--line);border-radius:11px;background:var(--panel);overflow:hidden}}.panel-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:15px 17px;border-bottom:1px solid var(--line)}}.panel-head h2,.panel-head h3{{margin:0;font-size:15px}}.panel-head p{{margin:4px 0 0;color:var(--muted);font-size:11px;line-height:1.55}}.panel-body{{padding:16px 17px}}.muted,.hint{{color:var(--muted);font-size:12px;line-height:1.65}}.hint{{margin:0}}.table-wrap{{overflow-x:auto}}table{{width:100%;min-width:720px;border-collapse:collapse}}th{{padding:10px 11px;background:rgba(4,13,25,.35);color:#7890b2;text-align:left;font-size:10px;letter-spacing:.04em;white-space:nowrap}}td{{padding:10px 11px;border-top:1px solid rgba(160,181,215,.09);color:#c8d6e9;font-size:12px;white-space:nowrap}}tbody tr:hover td{{background:rgba(246,200,95,.045)}}.ok{{color:var(--green)}}.bad{{color:#ff9cab}}.status-tag{{display:inline-flex;padding:4px 7px;border-radius:5px;font-size:10px;font-weight:700}}.status-tag.good{{background:rgba(85,214,160,.12);color:#a7f3d0}}.status-tag.bad{{background:rgba(251,113,133,.12);color:#fecdd3}}.status-tag.pending{{background:var(--gold-soft);color:#ffe7a4}}.status-tag.info{{background:rgba(116,185,255,.12);color:#bfdbfe}}
.filter-form{{display:flex;align-items:flex-end;gap:8px;flex-wrap:wrap}}.filter-form label{{display:grid;gap:5px;color:var(--muted);font-size:11px}}input,select{{height:34px;border:1px solid var(--line);border-radius:7px;background:#081529;color:var(--text);padding:0 9px}}input:focus,select:focus{{outline:2px solid rgba(246,200,95,.32);outline-offset:1px}}.pager{{display:flex;align-items:center;justify-content:flex-end;gap:12px;padding:12px 16px;color:var(--muted);font-size:11px}}.pager a{{color:var(--blue)}}.pager .disabled{{color:#536985;pointer-events:none}}.empty{{padding:26px 16px;color:var(--muted);font-size:12px;text-align:center}}
  .tabs{{display:flex;gap:6px;flex-wrap:wrap;padding:14px 16px 0}}.tab{{padding:7px 10px;border:1px solid transparent;border-radius:7px;color:#aebed4;font-size:12px}}.tab:hover,.tab.active{{background:var(--gold-soft);border-color:rgba(246,200,95,.22);color:#ffe7a4}}.details-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}.details-grid div{{padding:11px;border:1px solid rgba(160,181,215,.12);border-radius:8px;background:rgba(255,255,255,.025)}}.details-grid span{{display:block;color:var(--muted);font-size:10px;margin-bottom:4px}}.details-grid b{{font-size:13px}}.log-content{{margin:0;padding:16px;min-height:280px;overflow:auto;background:#050d19;color:#c9d8eb;font:12px/1.7 Consolas,"Noto Sans Mono CJK SC",monospace;white-space:pre-wrap;word-break:break-word}}
.inline-form{{display:inline-flex;margin:6px 0 0}}.button.danger{{border-color:rgba(251,113,133,.45);background:rgba(251,113,133,.1);color:#fecdd3}}.mutation-stack{{display:grid;gap:12px}}.mutation-card{{padding:14px;border:1px solid rgba(160,181,215,.13);border-radius:9px;background:rgba(255,255,255,.025)}}.mutation-card h3{{margin:0;font-size:13px}}.mutation-card .hint{{margin:6px 0 12px}}.danger-card{{border-color:rgba(251,113,133,.3)}}.mutation-form{{display:grid;grid-template-columns:repeat(2,minmax(0,260px));gap:9px;align-items:end}}.mutation-form label{{display:grid;gap:5px;color:var(--muted);font-size:11px}}.mutation-form textarea{{min-height:88px;resize:vertical;border:1px solid var(--line);border-radius:7px;background:#081529;color:var(--text);padding:8px 9px;font:inherit}}.mutation-form textarea:focus{{outline:2px solid rgba(246,200,95,.32);outline-offset:1px}}.notification-form .notification-body{{grid-column:1 / -1;max-width:529px}}.mutation-form .button{{justify-self:start}}
@media(max-width:980px){{.workspace{{display:block}}.sidebar{{padding:14px 18px;border-right:0;border-bottom:1px solid var(--line)}}.brand{{padding-bottom:12px;border-bottom:0}}.primary-nav-list{{display:flex;gap:6px;overflow-x:auto;margin-top:8px}}.primary-nav{{white-space:nowrap}}.secondary-nav-list{{display:flex;order:2;width:100%;margin:0;padding:0;border-left:0;overflow-x:auto}}.secondary-nav{{white-space:nowrap}}.main{{padding:18px}}}}
@media(max-width:620px){{.main{{padding:14px}}.topbar{{align-items:flex-start;flex-direction:column}}.top-actions{{justify-content:flex-start}}h1{{font-size:21px}}.metric-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.details-grid{{grid-template-columns:1fr 1fr}}.panel-head,.panel-body{{padding:14px}}}}
</style>
</head>
<body>
<div class="workspace">
<aside class="sidebar"><a class="brand" href="/admin">DocxTool 管理工作台<small>网页业务与 WPS 插件</small></a><nav class="primary-nav-list" aria-label="主导航">{navigation}</nav></aside>
<main class="main"><header class="topbar"><div><div class="title-kicker">ADMIN WORKSPACE</div><h1>{html.escape(title)}</h1></div><div class="top-actions">{status}<button class="button" type="button" onclick="window.location.reload()">刷新</button><a class="button" href="/">返回工具</a><form method="post" action="/admin/logout">{csrf_input}<button class="button" type="submit">退出</button></form></div></header>{body}</main>
</div>
<script>
document.querySelectorAll('form[data-confirm]').forEach(function(form){{form.addEventListener('submit',function(event){{if(!window.confirm(form.dataset.confirm||'确认执行此操作？')){{event.preventDefault();}}}});}});
</script>
</body>
</html>"""
