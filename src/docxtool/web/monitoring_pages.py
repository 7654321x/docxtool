"""管理员监控页面 HTML 渲染辅助。

本模块只把调用方传入的任务统计、IP 活动和安全状态渲染成 HTML，
不直接访问 HTTP handler、数据库、任务队列或 DOCX 识别链路。
"""

from __future__ import annotations

import html
from typing import Any, Callable, Mapping
from urllib.parse import quote

from docxtool.web.monitoring import monitor_url, normalize_monitor_query
from docxtool.web.request_utils import html_escape as _html_escape


def render_pager_html(stats: dict, admin_token: str, page_key: str, pages_key: str) -> str:
    """传入统计字典、管理员令牌和分页字段名，返回上一页/下一页 HTML。"""
    # admin_token 保留给旧调用签名；分页链接本身不再通过 URL 携带管理员令牌。
    _ = admin_token
    query = stats.get("query", normalize_monitor_query())
    page = int(stats.get(page_key, 1))
    pages = int(stats.get(pages_key, 1))
    prev_page = max(1, page - 1)
    next_page = min(pages, page + 1)
    prev_cls = " disabled" if page <= 1 else ""
    next_cls = " disabled" if page >= pages else ""
    prev_href = monitor_url(query, **{page_key: prev_page})
    next_href = monitor_url(query, **{page_key: next_page})
    return (
        f'<div class="pager">'
        f'<a class="{prev_cls}" href="{prev_href}">上一页</a>'
        f'<span>第 {page} / {pages} 页</span>'
        f'<a class="{next_cls}" href="{next_href}">下一页</a>'
        f'</div>'
    )


def status_badge(status: str) -> tuple[str, str]:
    """传入任务状态字符串，返回页面展示用的中文标签和 CSS 类名。"""
    mapping = {
        "done": ("完成", "done"),
        "error": ("失败", "error"),
        "timeout": ("超时", "error"),
        "failed": ("失败", "error"),
        "interrupted": ("中断", "error"),
        "expired": ("过期", "error"),
        "queued": ("排队中", "queued"),
        "processing": ("处理中", "processing"),
    }
    return mapping.get(status or "", (status or "-", "processing"))


def render_recent_task_rows(stats: Mapping[str, Any], admin_token: str, admin_url: Callable[[str, str], str]) -> str:
    """传入监控统计、管理员令牌和 URL 构造函数，返回最近任务表格行 HTML。"""
    rows = []
    for item in stats.get("recent", []):
        tag, cls = status_badge(item.get("status", ""))
        rows.append(
            f"<tr><td class=mono>{_html_escape(str(item.get('created_at','')))[:16]}</td>"
            f"<td class=fn title=\"{_html_escape(str(item.get('filename','-')))}\">{_html_escape(str(item.get('filename','-')))[:40]}</td>"
            f"<td class=mono>{_html_escape(item.get('ip','-'))}</td>"
            f"<td>{(item.get('file_size',0)/1024):.0f} KB</td>"
            f"<td>{_html_escape(item.get('doc_type','-'))}</td>"
            f"<td>{item.get('paragraphs',0)}</td>"
            f"<td>{((item.get('duration_ms',0) or 0)/1000):.1f}s</td>"
            f"<td><span class=\"status-tag {cls}\">{tag}</span></td>"
            f"<td><a class=\"table-action\" href=\"{admin_url('/log/' + _html_escape(item.get('id','')), admin_token)}\" target=\"_blank\">查看日志</a></td></tr>")
    return "".join(rows)


def render_top_ip_rows(
    stats: Mapping[str, Any],
    admin_token: str,
    csrf_input: str,
    admin_url: Callable[[str, str], str],
) -> str:
    """传入监控统计、管理员令牌、CSRF 隐藏域和 URL 构造函数，返回活跃 IP 表格行 HTML。"""
    return "".join(
        f"<tr><td class=mono>{_html_escape(r.get('ip','-'))}</td>"
            f"<td>{r.get('c',0)}</td><td class=ok>{r.get('done',0)}</td><td class=badtxt>{r.get('error',0)}</td>"
            f"<td class=mono>{_html_escape(str(r.get('last','')))[:16]}</td>"
            f"<td class=fn title=\"{_html_escape(r.get('last_filename','-'))}\">{_html_escape(r.get('last_filename','-'))[:32]}</td>"
        f"<td class=actions><a class=\"table-action\" href=\"{admin_url('/ip?addr=' + quote(str(r.get('ip','')), safe=''), admin_token)}\" target=\"_blank\">明细</a>"
        f"<form method=\"post\" action=\"/ban\" onsubmit=\"return confirm('确认封禁该 IP？')\">{csrf_input}<input type=\"hidden\" name=\"ip\" value=\"{_html_escape(r.get('ip',''))}\"><input type=\"hidden\" name=\"reason\" value=\"monitor\"><button class=\"link-danger\" type=\"submit\">封禁</button></form></td></tr>"
        for r in stats.get("top_ips", []))


def render_banned_ip_rows(stats: Mapping[str, Any], csrf_input: str) -> str:
    """传入监控统计和 CSRF 隐藏域，返回封禁 IP 表格行 HTML。"""
    return "".join(
        f"<tr><td class=mono>{_html_escape(r.get('ip','-'))}</td>"
        f"<td>{_html_escape(r.get('reason',''))}</td>"
        f"<td class=mono>{_html_escape(str(r.get('created_at','')))[:16]}</td>"
        f"<td><form method=\"post\" action=\"/unban\">{csrf_input}<input type=\"hidden\" name=\"ip\" value=\"{_html_escape(r.get('ip',''))}\"><button class=\"link-danger\" type=\"submit\">解封</button></form></td></tr>"
        for r in stats.get("banned_ips", []))


def render_trend_bars(trend: list[Mapping[str, Any]]) -> str:
    """传入按日趋势列表，返回最近 14 条趋势条 HTML。"""
    max_trend = max([int(item.get("total", 0) or 0) for item in trend] + [1])
    return "".join(
        f"<div class=\"trend-row\"><span class=\"trend-date\">{_html_escape(item.get('date', '-'))}</span>"
        f"<div class=\"trend-track\"><i class=\"trend-done\" style=\"width:{max(2, int(item.get('done', 0) or 0) / max_trend * 100):.1f}%\"></i>"
        f"<i class=\"trend-error\" style=\"width:{max(0, int(item.get('error', 0) or 0) / max_trend * 100):.1f}%\"></i></div>"
        f"<span class=\"trend-count\">{item.get('total', 0)}<small>项</small></span></div>"
        for item in trend[-14:]) or '<div class="empty-state">暂无趋势数据，完成任务后将在此显示。</div>'


def render_health_check_items(ready: Mapping[str, Any]) -> str:
    """传入 readiness payload，返回数据库、输出目录和日志目录检查项 HTML。"""
    checks = ready.get("checks", {})
    return "".join(
        f"<li class={'check-ok' if value else 'check-bad'}><span></span>{_html_escape(label)}<b>{'正常' if value else '异常'}</b></li>"
        for label, value in (("数据库", checks.get("database")), ("输出目录", checks.get("output_dir")), ("日志目录", checks.get("log_dir")))
    )


def render_task_log_html(task_id: str, row: Mapping[str, Any] | None, log_text: str) -> str:
    """传入任务 ID、任务行数据和已脱敏日志文本，返回任务日志 HTML。"""
    filename = _html_escape(_row_get(row, "filename", "-"))
    status = _html_escape(_row_get(row, "status", "-"))
    duration = ((_row_get(row, "duration_ms", 0) or 0) / 1000) if row else 0
    error_code = _html_escape(_row_get(row, "error_code", "") or "-")
    created_at = _html_escape(_row_get(row, "created_at", "-"))
    escaped_log = _html_escape(log_text)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>任务日志 · {filename}</title><style>
:root{{--bg:#07101f;--panel:#0d1a2e;--line:rgba(160,181,215,.17);--text:#edf4ff;--muted:#8fa2be;--gold:#f6c85f;--red:#fb7185}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","Noto Sans CJK SC","PingFang SC",sans-serif}}.page{{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:22px 0 36px}}.topbar{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;padding-bottom:17px;border-bottom:1px solid var(--line)}}.eyebrow{{color:var(--gold);font-size:10px;letter-spacing:.12em;margin-bottom:5px}}h1{{font-size:20px;margin:0;max-width:780px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.actions{{display:flex;gap:8px}}.btn{{height:34px;padding:0 11px;border:1px solid var(--line);border-radius:7px;background:rgba(255,255,255,.04);color:#b9c9df;font-size:11px;display:inline-flex;align-items:center;cursor:pointer;text-decoration:none}}.btn:hover{{border-color:rgba(246,200,95,.4);color:#ffe7a4}}.meta{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:18px 0}}.meta div{{padding:13px;border:1px solid var(--line);border-radius:9px;background:var(--panel)}}.meta span{{display:block;color:var(--muted);font-size:10px;margin-bottom:5px}}.meta b{{font-size:13px;font-weight:650}}.log-panel{{border:1px solid var(--line);border-radius:11px;overflow:hidden;background:#050d19}}.log-head{{padding:12px 15px;border-bottom:1px solid var(--line);color:#9eb1cb;font-size:11px}}pre{{margin:0;padding:18px;min-height:360px;overflow:auto;color:#c9d8eb;font:12px/1.75 Consolas,"Noto Sans Mono CJK SC",monospace;white-space:pre-wrap;word-break:break-word}}@media(max-width:700px){{.topbar{{flex-direction:column}}.meta{{grid-template-columns:1fr 1fr}}h1{{white-space:normal}}}}
</style></head><body><main class="page"><header class="topbar"><div><div class="eyebrow">TASK LOG / {_html_escape(task_id)}</div><h1>{filename}</h1></div><div class="actions"><a class="btn" href="/monitor#tasks">返回工作台</a><button class="btn" type="button" onclick="navigator.clipboard.writeText(document.getElementById('taskLog').textContent).then(()=>this.textContent='已复制')">复制日志</button></div></header><section class="meta"><div><span>任务状态</span><b>{status}</b></div><div><span>创建时间</span><b>{created_at}</b></div><div><span>处理耗时</span><b>{duration:.1f}s</b></div><div><span>错误码</span><b>{error_code}</b></div></section><section class="log-panel"><div class="log-head">日志内容 · 已自动隐藏敏感认证字段</div><pre id="taskLog">{escaped_log}</pre></section></main></body></html>"""


def render_ip_detail_html(
    ip: str,
    admin_token: str = "",
    *,
    csrf_hidden_input: Callable[[str], str],
    ip_activity: Callable[[str], list],
    ip_upload_count: Callable[[str, int], int],
    is_ip_banned: Callable[[str], bool],
    admin_url: Callable[[str, str], str],
) -> str:
    """传入 IP、管理员令牌和查询回调，返回管理员 IP 明细 HTML。"""
    csrf_input = csrf_hidden_input(admin_token)
    rows = []
    for item in ip_activity(ip):
        # IP 明细页沿用旧展示：非完成状态统一按失败显示，避免改变页面语义。
        st = item.get("status", "")
        tag = "完成" if st == "done" else "失败"
        cls = "done" if st == "done" else "error"
        rows.append(
            f"<tr><td class=mono>{_html_escape(str(item.get('created_at','')))[:19]}</td>"
            f"<td class=fn>{_html_escape(item.get('filename','-'))[:60]}</td>"
            f"<td>{(item.get('file_size',0)/1024):.0f}KB</td>"
            f"<td>{item.get('paragraphs',0)}</td>"
            f"<td>{((item.get('duration_ms',0) or 0)/1000):.1f}s</td>"
            f"<td><span class=\"status-tag {cls}\">{tag}</span></td>"
            f"<td><a class=\"action-link\" href=\"{admin_url('/log/' + _html_escape(item.get('id','')), admin_token)}\" target=\"_blank\">查看日志</a></td></tr>")
    total = ip_upload_count(ip, 0)
    last_hour = ip_upload_count(ip, 3600)
    banned = is_ip_banned(ip)
    action = (f"<form method=\"post\" action=\"/unban\">{csrf_input}<input type=\"hidden\" name=\"ip\" value=\"{_html_escape(ip)}\"><button class=\"danger-btn\" type=\"submit\">解封 IP</button></form>"
              if banned else
              f"<form method=\"post\" action=\"/ban\" onsubmit=\"return confirm('确认封禁该 IP？')\">{csrf_input}<input type=\"hidden\" name=\"ip\" value=\"{_html_escape(ip)}\"><input type=\"hidden\" name=\"reason\" value=\"monitor\"><button class=\"danger-btn\" type=\"submit\">封禁 IP</button></form>")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>IP 明细 · {html.escape(ip)}</title>
<style>
:root{{--bg:#07101f;--panel:#0d1a2e;--line:rgba(160,181,215,.17);--text:#edf4ff;--muted:#8fa2be;--gold:#f6c85f;--green:#55d6a0;--red:#fb7185}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","Noto Sans CJK SC","WenQuanYi Micro Hei","PingFang SC",Arial,sans-serif}}.page{{width:min(1180px,calc(100% - 36px));margin:0 auto;padding:24px 0 40px}}.topbar{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding-bottom:18px;border-bottom:1px solid var(--line)}}.nav{{display:flex;gap:9px;align-items:center}}.nav a,.danger-btn{{height:34px;padding:0 11px;border:1px solid var(--line);border-radius:7px;background:rgba(255,255,255,.04);color:#b9c9df;text-decoration:none;font-size:11px;display:inline-flex;align-items:center;cursor:pointer}}.danger-btn{{border-color:rgba(251,113,133,.28);background:rgba(251,113,133,.08);color:#fecdd3}}.nav form{{margin:0}}.eyebrow{{color:var(--gold);font-size:10px;letter-spacing:.12em;margin-bottom:5px}}h1{{font-size:22px;margin:0}}.mono{{font-family:Consolas,"Noto Sans Mono CJK SC","WenQuanYi Micro Hei",monospace;font-size:11px}}.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:20px 0}}.card{{padding:16px;border:1px solid var(--line);border-radius:10px;background:linear-gradient(145deg,rgba(18,35,59,.9),rgba(10,24,42,.9))}}.n{{font-size:23px;font-weight:800;color:#f6d985}}.card div:last-child{{font-size:11px;color:var(--muted);margin-top:5px}}.panel{{border:1px solid var(--line);border-radius:12px;background:var(--panel);overflow:hidden}}.panel-head{{padding:16px 18px;border-bottom:1px solid var(--line)}}.panel-head h2{{font-size:15px;margin:0}}.panel-head p{{font-size:11px;color:var(--muted);margin:4px 0 0}}.table-wrap{{overflow-x:auto}}table{{width:100%;min-width:780px;border-collapse:collapse}}th{{background:rgba(4,13,25,.4);text-align:left;padding:10px 11px;color:#7890b2;font-size:10px}}td{{font-size:12px;padding:10px 11px;border-top:1px solid rgba(160,181,215,.09);color:#c8d6e9;white-space:nowrap}}.fn{{max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.status-tag{{display:inline-flex;padding:4px 7px;border-radius:5px;font-size:10px;font-weight:700}}.status-tag.done{{background:rgba(85,214,160,.12);color:#a7f3d0}}.status-tag.error{{background:rgba(251,113,133,.12);color:#fecdd3}}.status-tag.processing{{background:rgba(116,185,255,.12);color:#bfdbfe}}.action-link{{color:#9bc8ff;text-decoration:none;font-size:11px}}.empty{{padding:28px;text-align:center;color:var(--muted)}}@media(max-width:640px){{.page{{width:min(100% - 24px,1180px);padding-top:14px}}.topbar{{align-items:flex-start;flex-direction:column}}.cards{{grid-template-columns:1fr}}}}
</style></head><body>
<main class="page"><header class="topbar"><div><div class="eyebrow">SECURITY / IP DETAIL</div><h1>IP 上传明细：<span class="mono">{html.escape(ip)}</span></h1></div><div class="nav"><a href="/monitor#security">返回工作台</a>{action}</div></header>
<div class="cards"><div class="card"><div class="n">{total}</div><div>总上传次数</div></div>
<div class="card"><div class="n">{last_hour}</div><div>最近 1 小时</div></div>
<div class="card"><div class="n">{"已封禁" if banned else "正常"}</div><div>当前状态</div></div></div>
<section class="panel"><div class="panel-head"><h2>任务记录</h2><p>该 IP 最近关联的排版任务和处理状态</p></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>文件名</th><th>大小</th><th>段数</th><th>耗时</th><th>状态</th><th>日志</th></tr></thead><tbody>{"".join(rows) or '<tr><td colspan="7"><div class="empty">暂无上传记录</div></td></tr>'}</tbody></table></div></section></main>
</body></html>"""


def _row_get(row: Mapping[str, Any] | None, key: str, default: Any = "") -> Any:
    """传入可映射的数据库行和字段名，返回字段值；缺失时返回默认值。"""
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default
