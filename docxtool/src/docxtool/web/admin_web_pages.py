"""Server-rendered pages for the Web business section of the administrator workspace."""

from __future__ import annotations

import html
from collections.abc import Mapping
from urllib.parse import urlencode

from .admin_shell import render_admin_shell


_TASK_STATUSES = (
    ("", "全部状态"),
    ("queued", "排队中"),
    ("processing", "处理中"),
    ("done", "完成"),
    ("error", "失败"),
    ("timeout", "超时"),
    ("failed", "失败"),
    ("interrupted", "中断"),
    ("expired", "已过期"),
)


def _escape(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _task_status(value: object) -> tuple[str, str]:
    raw = str(value or "")
    mapping = {
        "done": ("完成", "good"),
        "queued": ("排队中", "pending"),
        "processing": ("处理中", "info"),
        "error": ("失败", "bad"),
        "timeout": ("超时", "bad"),
        "failed": ("失败", "bad"),
        "interrupted": ("中断", "bad"),
        "expired": ("已过期", "bad"),
    }
    return mapping.get(raw, (raw or "-", "info"))


def _task_query_url(section: str, query: Mapping[str, object], **overrides: object) -> str:
    values = {
        "q": str(query.get("task_q", "") or ""),
        "status": str(query.get("task_status", "") or ""),
        "page": str(query.get("recent_page", 1) or 1),
        "page_size": str(query.get("recent_size", 20) or 20),
    }
    values.update({key: str(value) for key, value in overrides.items()})
    values = {key: value for key, value in values.items() if value and not (key == "page" and value == "1")}
    suffix = urlencode(values)
    return f"/admin/web/{section}" + (f"?{suffix}" if suffix else "")


def _pager(section: str, query: Mapping[str, object], total: int, page: int, pages: int) -> str:
    previous = _task_query_url(section, query, page=max(1, page - 1))
    following = _task_query_url(section, query, page=min(pages, page + 1))
    previous_class = " disabled" if page <= 1 else ""
    following_class = " disabled" if page >= pages else ""
    return (
        f'<div class="pager"><span>共 {int(total)} 条，第 {int(page)} / {int(pages)} 页</span>'
        f'<a class="{previous_class.strip()}" href="{_escape(previous)}">上一页</a>'
        f'<a class="{following_class.strip()}" href="{_escape(following)}">下一页</a></div>'
    )


def _task_filter(section: str, query: Mapping[str, object]) -> str:
    current_status = str(query.get("task_status", "") or "")
    options = "".join(
        f'<option value="{_escape(value)}"{" selected" if value == current_status else ""}>{_escape(label)}</option>'
        for value, label in _TASK_STATUSES
    )
    return f"""<form class="filter-form" method="get" action="/admin/web/{_escape(section)}">
<label>关键词<input name="q" value="{_escape(query.get('task_q', ''))}" placeholder="任务编号或文件名"></label>
<label>状态<select name="status">{options}</select></label>
<label>每页<select name="page_size"><option value="20"{' selected' if int(query.get('recent_size', 20)) == 20 else ''}>20</option><option value="50"{' selected' if int(query.get('recent_size', 20)) == 50 else ''}>50</option><option value="100"{' selected' if int(query.get('recent_size', 20)) == 100 else ''}>100</option></select></label>
<button class="button primary" type="submit">查询</button><a class="button" href="/admin/web/{_escape(section)}">清除</a></form>"""


def _task_rows(stats: Mapping[str, object], *, include_log: bool) -> str:
    rows = []
    for row in stats.get("recent", []):
        if not isinstance(row, Mapping):
            continue
        label, class_name = _task_status(row.get("status"))
        log_cell = (
            f'<td><a class="ok" href="{_escape("/admin/web/logs?" + urlencode({"task_id": str(row.get("id") or "")}))}">查看日志</a></td>'
            if include_log
            else ""
        )
        rows.append(
            f'<tr><td>{_escape(row.get("created_at", "-"))}</td><td>{_escape(row.get("id", "-"))}</td>'
            f'<td>{_escape(row.get("filename", "-"))}</td><td><span class="status-tag {class_name}">{label}</span></td>'
            f'<td>{_escape(row.get("doc_type", "-"))}</td><td>{int(row.get("paragraphs", 0) or 0)}</td>'
            f'<td>{(int(row.get("duration_ms", 0) or 0) / 1000):.1f}s</td><td>{_escape(row.get("error_code", "-") or "-")}</td>{log_cell}</tr>'
        )
    colspan = 9 if include_log else 8
    return "".join(rows) or f'<tr><td colspan="{colspan}"><div class="empty">没有符合条件的任务</div></td></tr>'


def _render_tasks(stats: Mapping[str, object], query: Mapping[str, object]) -> str:
    filter_html = _task_filter("tasks", query)
    rows = _task_rows(stats, include_log=True)
    return f"""<div class="metric-grid"><div class="metric"><b>{int(stats.get('total', 0) or 0)}</b><span>匹配任务</span></div><div class="metric good"><b>{int(stats.get('done', 0) or 0)}</b><span>完成</span></div><div class="metric bad"><b>{int(stats.get('error', 0) or 0)}</b><span>失败</span></div><div class="metric"><b>{float(stats.get('rate', 0) or 0):.1f}%</b><span>完成率</span></div></div>
<section class="panel"><div class="panel-head"><div><h2>任务中心</h2><p>查看网页排版任务、处理状态和可用日志入口</p></div>{filter_html}</div><div class="table-wrap"><table><thead><tr><th>创建时间</th><th>任务编号</th><th>文件</th><th>状态</th><th>类型</th><th>段落</th><th>耗时</th><th>错误码</th><th>日志</th></tr></thead><tbody>{rows}</tbody></table></div>{_pager('tasks', query, int(stats.get('recent_total', 0) or 0), int(stats.get('recent_page', 1) or 1), int(stats.get('recent_pages', 1) or 1))}</section>"""


def _render_security(stats: Mapping[str, object], csrf_input: str) -> str:
    top_rows = []
    for item in stats.get("top_ips", []):
        if not isinstance(item, Mapping):
            continue
        raw_ip = str(item.get("ip", "") or "")
        ip = _escape(raw_ip)
        detail_href = "/admin/web/security?" + urlencode({"ip": raw_ip})
        top_rows.append(
            f'<tr><td>{ip}</td><td>{int(item.get("c", 0) or 0)}</td><td class="ok">{int(item.get("done", 0) or 0)}</td>'
            f'<td class="bad">{int(item.get("error", 0) or 0)}</td><td>{_escape(item.get("last", "-"))}</td>'
            f'<td><a class="ok" href="{_escape(detail_href)}">详情</a></td><td><form method="post" action="/ban">{csrf_input}<input type="hidden" name="ip" value="{ip}"><input type="hidden" name="reason" value="admin_workspace"><button class="button" type="submit">封禁</button></form></td></tr>'
        )
    banned_rows = []
    for item in stats.get("banned_ips", []):
        if not isinstance(item, Mapping):
            continue
        ip = _escape(item.get("ip", ""))
        banned_rows.append(
            f'<tr><td>{ip}</td><td>{_escape(item.get("reason", ""))}</td><td>{_escape(item.get("created_at", "-"))}</td>'
            f'<td><form method="post" action="/unban">{csrf_input}<input type="hidden" name="ip" value="{ip}"><button class="button" type="submit">解封</button></form></td></tr>'
        )
    return f"""<div class="metric-grid"><div class="metric"><b>{int(stats.get('unique_ips', 0) or 0)}</b><span>访问 IP</span></div><div class="metric"><b>{len(stats.get('banned_ips', []))}</b><span>已封禁 IP</span></div><div class="metric"><b>{float(stats.get('total_mb', 0) or 0):.1f} MB</b><span>累计上传</span></div><div class="metric"><b>{float(stats.get('avg_s', 0) or 0):.1f}s</b><span>平均处理</span></div></div>
<section class="panel"><div class="panel-head"><div><h2>活跃 IP</h2><p>按最近任务活动排序；封禁操作沿用现有管理员 CSRF 边界</p></div></div><div class="table-wrap"><table><thead><tr><th>IP</th><th>任务</th><th>完成</th><th>失败</th><th>最近活动</th><th>详情</th><th>操作</th></tr></thead><tbody>{''.join(top_rows) or '<tr><td colspan="7"><div class="empty">暂无 IP 活动</div></td></tr>'}</tbody></table></div></section>
<section class="panel"><div class="panel-head"><div><h2>封禁列表</h2><p>仅显示已有的封禁记录</p></div></div><div class="table-wrap"><table><thead><tr><th>IP</th><th>原因</th><th>创建时间</th><th>操作</th></tr></thead><tbody>{''.join(banned_rows) or '<tr><td colspan="4"><div class="empty">当前没有封禁记录</div></td></tr>'}</tbody></table></div></section>"""


def _render_runtime(readiness: Mapping[str, object], runtime: Mapping[str, object], limit: Mapping[str, object], csrf_input: str) -> str:
    checks = readiness.get("checks", {}) if isinstance(readiness.get("checks"), Mapping) else {}
    check_rows = "".join(
        f'<tr><td>{_escape(name)}</td><td class="{"ok" if value else "bad"}">{"正常" if value else "异常"}</td></tr>'
        for name, value in checks.items()
    ) or '<tr><td colspan="2"><div class="empty">没有可用的健康检查数据</div></td></tr>'
    enabled = " checked" if bool(limit.get("enabled")) else ""
    return f"""<div class="metric-grid"><div class="metric"><b>{int(runtime.get('queued', 0) or 0)}</b><span>排队任务</span></div><div class="metric"><b>{int(runtime.get('processing', 0) or 0)}</b><span>处理中</span></div><div class="metric"><b>{int(runtime.get('max_workers', 0) or 0)}</b><span>并发上限</span></div><div class="metric"><b>{_escape(runtime.get('version', '-'))}</b><span>服务版本</span></div></div>
<section class="panel"><div class="panel-head"><div><h2>上传限额</h2><p>沿用现有访问频率限制配置</p></div></div><div class="panel-body"><form class="filter-form" method="post" action="/limit">{csrf_input}<label>状态<span><input type="checkbox" name="enabled" value="1"{enabled}> 启用</span></label><label>时间窗口（秒）<input type="number" min="1" name="window_seconds" value="{int(limit.get('window_seconds', 0) or 0)}"></label><label>允许次数<input type="number" min="1" name="count" value="{int(limit.get('count', 0) or 0)}"></label><button class="button primary" type="submit">保存设置</button></form></div></section>
<section class="panel"><div class="panel-head"><div><h2>就绪检查</h2><p>只展示当前服务实际提供的健康结果</p></div></div><div class="table-wrap"><table><thead><tr><th>检查项</th><th>结果</th></tr></thead><tbody>{check_rows}</tbody></table></div></section>"""


def _render_logs(stats: Mapping[str, object], query: Mapping[str, object]) -> str:
    filter_html = _task_filter("logs", query)
    rows = _task_rows(stats, include_log=True)
    return f"""<section class="panel"><div class="panel-head"><div><h2>日志查询</h2><p>按任务编号、文件名或状态筛选，并打开已有的脱敏任务日志</p></div>{filter_html}</div><div class="table-wrap"><table><thead><tr><th>创建时间</th><th>任务编号</th><th>文件</th><th>状态</th><th>类型</th><th>段落</th><th>耗时</th><th>错误码</th><th>日志</th></tr></thead><tbody>{rows}</tbody></table></div>{_pager('logs', query, int(stats.get('recent_total', 0) or 0), int(stats.get('recent_page', 1) or 1), int(stats.get('recent_pages', 1) or 1))}</section>"""


def _row_value(row: object, key: str, default: object = "") -> object:
    """Read a field from either a mapping or a SQLite row without inventing a missing value."""
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return default


def render_admin_web_ip_detail_page(
    *,
    ip: str,
    activity: list[Mapping[str, object]],
    total: int,
    last_hour: int,
    banned: bool,
    csrf_input: str,
    readiness: Mapping[str, object],
) -> str:
    """Render one validated IP detail inside the canonical Web security page shell."""
    rows = []
    for item in activity:
        label, class_name = _task_status(item.get("status"))
        log_href = "/admin/web/logs?" + urlencode({"task_id": str(item.get("id") or "")})
        rows.append(
            f'<tr><td>{_escape(item.get("created_at", "-"))}</td><td>{_escape(item.get("filename", "-"))}</td>'
            f'<td>{int(item.get("file_size", 0) or 0) // 1024} KB</td><td>{int(item.get("paragraphs", 0) or 0)}</td>'
            f'<td>{int(item.get("duration_ms", 0) or 0) / 1000:.1f}s</td>'
            f'<td><span class="status-tag {class_name}">{_escape(label)}</span></td>'
            f'<td><a class="ok" href="{_escape(log_href)}">查看日志</a></td></tr>'
        )
    action = (
        f'<form method="post" action="/unban">{csrf_input}<input type="hidden" name="ip" value="{_escape(ip)}">'
        '<button class="button" type="submit">解封 IP</button></form>'
        if banned
        else f'<form method="post" action="/ban">{csrf_input}<input type="hidden" name="ip" value="{_escape(ip)}">'
        '<input type="hidden" name="reason" value="admin_workspace"><button class="button primary" type="submit">封禁 IP</button></form>'
    )
    body = f"""<div class="metric-grid"><div class="metric"><b>{int(total)}</b><span>总上传次数</span></div><div class="metric"><b>{int(last_hour)}</b><span>最近 1 小时</span></div><div class="metric {'bad' if banned else 'good'}"><b>{'已封禁' if banned else '正常'}</b><span>当前状态</span></div></div>
<section class="panel"><div class="panel-head"><div><h2>IP 详情：{_escape(ip)}</h2><p>该 IP 关联的最近网页排版任务和安全状态。</p></div><div class="top-actions"><a class="button" href="/admin/web/security">返回安全与访问</a>{action}</div></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>文件名</th><th>大小</th><th>段落</th><th>耗时</th><th>状态</th><th>日志</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="7"><div class="empty">暂无该 IP 的任务记录</div></td></tr>'}</tbody></table></div></section>"""
    return render_admin_shell(
        title="安全与访问 · IP 详情",
        active_module="web",
        active_page="security",
        body=body,
        csrf_input=csrf_input,
        service_status={"web": bool(readiness.get("ok"))},
    )


def render_admin_web_task_log_page(
    *, task_id: str, row: object, log_text: str, readiness: Mapping[str, object]
) -> str:
    """Render an already-redacted task log inside the canonical logs page shell."""
    body = f"""<section class="panel"><div class="panel-head"><div><h2>任务日志：{_escape(task_id)}</h2><p>日志内容已按现有规则脱敏；不显示本机绝对路径或认证凭据。</p></div><a class="button" href="/admin/web/logs">返回日志查询</a></div><div class="panel-body"><div class="details-grid"><div><span>文件</span><b>{_escape(_row_value(row, 'filename', '-'))}</b></div><div><span>状态</span><b>{_escape(_row_value(row, 'status', '-'))}</b></div><div><span>创建时间</span><b>{_escape(_row_value(row, 'created_at', '-'))}</b></div><div><span>处理耗时</span><b>{int(_row_value(row, 'duration_ms', 0) or 0) / 1000:.1f}s</b></div><div><span>错误码</span><b>{_escape(_row_value(row, 'error_code', '-') or '-')}</b></div></div></div><pre class="log-content">{_escape(log_text)}</pre></section>"""
    return render_admin_shell(
        title="日志查询 · 任务详情",
        active_module="web",
        active_page="logs",
        body=body,
        csrf_input="",
        service_status={"web": bool(readiness.get("ok"))},
    )


def render_admin_web_page(
    *,
    section: str,
    stats: Mapping[str, object],
    query: Mapping[str, object],
    readiness: Mapping[str, object],
    runtime: Mapping[str, object],
    limit: Mapping[str, object],
    csrf_input: str,
) -> str:
    """Render one Web business subpage inside the shared administrator shell."""
    pages = {
        "tasks": ("任务中心", _render_tasks(stats, query)),
        "security": ("安全与访问", _render_security(stats, csrf_input)),
        "runtime": ("运行设置", _render_runtime(readiness, runtime, limit, csrf_input)),
        "logs": ("日志查询", _render_logs(stats, query)),
    }
    title, body = pages.get(section, pages["tasks"])
    return render_admin_shell(
        title=title,
        active_module="web",
        active_page=section if section in pages else "tasks",
        body=body,
        csrf_input=csrf_input,
        service_status={"web": bool(readiness.get("ok"))},
    )
