"""管理员监控仪表盘整页 HTML 渲染辅助。

本模块只负责把调用方传入的统计数据、运行状态和局部 HTML 片段拼装成监控整页，不查询
数据库、不读取任务表，也不触碰 DOCX 识别或渲染链路。
"""

from __future__ import annotations

import html
from collections.abc import Callable


def render_monitor_dashboard_html(
    stats: dict,
    admin_token: str = "",
    *,
    limit_settings: Callable[[], dict],
    csrf_hidden_input: Callable[[str], str],
    normalize_monitor_query: Callable[[], dict],
    pager_html: Callable[[dict, str, str, str], str],
    ready_payload: Callable[[], dict],
    version_payload: Callable[[], dict],
    render_recent_task_rows: Callable[..., list[str]],
    render_top_ip_rows: Callable[..., str],
    render_banned_ip_rows: Callable[..., str],
    render_trend_bars: Callable[[list], str],
    render_health_check_items: Callable[[dict], str],
    admin_url: Callable[..., str],
    html_escape: Callable[[str], str],
    now_local: Callable[[], str],
    max_monitor_page_size: int,
) -> str:
    """传入统计数据和页面依赖回调，返回管理员监控仪表盘 HTML 字符串。"""
    limit = limit_settings()
    limit_checked = " checked" if limit["enabled"] else ""
    limit_state = "已开启" if limit["enabled"] else "已关闭"
    csrf_input = csrf_hidden_input(admin_token)
    query = stats.get("query", normalize_monitor_query())
    recent_pager = pager_html(stats, admin_token, "recent_page", "recent_pages")
    ip_pager = pager_html(stats, admin_token, "ip_page", "ip_pages")
    ready = ready_payload()
    version = version_payload()
    ready_state = "在线" if ready.get("ok") else "需检查"
    ready_class = "online" if ready.get("ok") else "offline"
    trend = stats.get("trend", [])
    rows = render_recent_task_rows(stats, admin_token, admin_url)
    ips = render_top_ip_rows(stats, admin_token, csrf_input, admin_url)
    banned_rows = render_banned_ip_rows(stats, csrf_input)
    trend_bars = render_trend_bars(trend)
    check_items = render_health_check_items(ready)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>工作台 · 公文智能排版</title>
<style>
:root{{--bg:#07101f;--panel:#0d1a2e;--panel2:#111f35;--line:rgba(160,181,215,.17);--muted:#8fa2be;--text:#edf4ff;--gold:#f6c85f;--gold-soft:rgba(246,200,95,.12);--blue:#74b9ff;--green:#55d6a0;--red:#fb7185}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{font-family:"Microsoft YaHei","Noto Sans CJK SC","WenQuanYi Micro Hei","PingFang SC",Arial,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
a{{color:inherit;text-decoration:none}}button,input{{font:inherit}}
.shell{{display:grid;grid-template-columns:224px minmax(0,1fr);min-height:100vh}}
.sidebar{{position:sticky;top:0;height:100vh;padding:24px 16px;border-right:1px solid var(--line);background:linear-gradient(180deg,#0b1729,#07101f);display:flex;flex-direction:column}}
.brand{{display:flex;align-items:center;gap:11px;padding:0 8px 25px;border-bottom:1px solid var(--line)}}
.brand-mark{{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,#f6c85f,#e89c3a);color:#152238;font-weight:900;font-size:18px}}
.brand strong{{display:block;font-size:14px;letter-spacing:.02em}}.brand small{{display:block;color:var(--muted);font-size:11px;margin-top:3px}}
.nav-label{{color:#637a9c;font-size:10px;letter-spacing:.12em;margin:24px 10px 8px;text-transform:uppercase}}
.side-nav{{display:grid;gap:5px}}.side-nav a{{display:flex;align-items:center;gap:10px;padding:11px 12px;border:1px solid transparent;border-radius:10px;color:#b8c8df;font-size:13px;transition:.18s}}
.side-nav a:hover,.side-nav a.active{{background:var(--gold-soft);border-color:rgba(246,200,95,.2);color:#ffe7a4}}
.nav-index{{width:22px;color:var(--gold);font-family:Consolas,monospace;font-size:11px}}
.side-footer{{margin-top:auto;padding:13px 10px;border-top:1px solid var(--line);color:var(--muted);font-size:11px;line-height:1.7}}
.side-footer b{{color:#cfe0f8;font-weight:600}}
.main{{min-width:0;padding:22px 30px 40px}}
.topbar{{display:flex;justify-content:space-between;align-items:center;gap:18px;padding-bottom:18px;border-bottom:1px solid var(--line)}}
.eyebrow{{color:var(--gold);font-size:11px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px}}h1{{font-size:24px;letter-spacing:.01em}}
.top-actions{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;justify-content:flex-end}}
.service-pill{{display:inline-flex;align-items:center;gap:7px;padding:8px 11px;border:1px solid rgba(85,214,160,.25);background:rgba(85,214,160,.08);border-radius:999px;color:#a7f3d0;font-size:12px}}
.service-pill.offline{{border-color:rgba(251,113,133,.3);background:rgba(251,113,133,.08);color:#fecdd3}}.service-dot{{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px rgba(85,214,160,.12)}}.offline .service-dot{{background:var(--red);box-shadow:0 0 0 4px rgba(251,113,133,.12)}}
.top-link,.top-button{{padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.04);color:#b9c9df;font-size:12px;cursor:pointer}}.top-link:hover,.top-button:hover{{border-color:rgba(246,200,95,.4);color:#ffe7a4}}
.alert{{display:flex;gap:12px;align-items:flex-start;padding:12px 14px;margin:18px 0;border:1px solid rgba(251,113,133,.3);border-radius:10px;background:rgba(251,113,133,.09);color:#fecdd3;font-size:12px;line-height:1.6}}
.section{{scroll-margin-top:20px;margin-top:24px}}.section-heading{{display:flex;justify-content:space-between;align-items:flex-end;gap:14px;margin-bottom:12px}}.section-heading h2{{font-size:16px}}.section-heading p{{color:var(--muted);font-size:12px;margin-top:4px}}.section-meta{{color:var(--muted);font-size:12px}}
.metric-grid{{display:grid;grid-template-columns:repeat(8,minmax(100px,1fr));gap:9px}}
.metric{{min-width:0;padding:15px 14px;border:1px solid var(--line);border-radius:10px;background:linear-gradient(145deg,rgba(18,35,59,.9),rgba(10,24,42,.9))}}.metric .value{{font-size:24px;color:#f6d985;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.metric .label{{color:var(--muted);font-size:11px;margin-top:6px}}.metric.good .value{{color:var(--green)}}.metric.bad .value{{color:#ff9cab}}
.work-grid{{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(270px,.8fr);gap:14px}}.panel{{min-width:0;border:1px solid var(--line);border-radius:12px;background:linear-gradient(145deg,rgba(14,30,51,.96),rgba(9,21,37,.96));overflow:hidden}}.panel-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:17px 18px;border-bottom:1px solid var(--line)}}.panel-head h3{{font-size:14px}}.panel-head p{{color:var(--muted);font-size:11px;margin-top:4px}}.panel-body{{padding:17px 18px}}
.health-list{{display:grid;gap:9px}}.health-list li{{list-style:none;display:flex;align-items:center;gap:9px;color:#b9c9df;font-size:12px}}.health-list li span{{width:7px;height:7px;border-radius:50%;background:var(--green)}}.health-list li.check-bad span{{background:var(--red)}}.health-list li b{{margin-left:auto;font-size:11px;color:var(--green);font-weight:600}}.health-list li.check-bad b{{color:#ff9cab}}
.runtime-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}}.runtime-item{{padding:10px;border-radius:8px;background:rgba(255,255,255,.04);border:1px solid rgba(160,181,215,.1)}}.runtime-item b{{display:block;font-size:15px;color:#e6effd}}.runtime-item span{{display:block;color:var(--muted);font-size:10px;margin-top:4px}}
.trend{{display:grid;gap:8px}}.trend-row{{display:grid;grid-template-columns:86px minmax(0,1fr) 42px;gap:10px;align-items:center}}.trend-date,.trend-count{{color:var(--muted);font-size:11px}}.trend-count{{text-align:right;color:#dce8fa}}.trend-count small{{color:var(--muted);margin-left:2px}}.trend-track{{height:12px;display:flex;gap:2px;background:rgba(255,255,255,.06);border-radius:99px;overflow:hidden}}.trend-track i{{display:block;height:100%;min-width:0}}.trend-done{{background:var(--green)}}.trend-error{{background:var(--red)}}
.legend{{display:flex;gap:14px;margin-top:15px;color:var(--muted);font-size:11px}}.legend i{{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px}}.legend .done{{background:var(--green)}}.legend .error{{background:var(--red)}}
.table-wrap{{overflow-x:auto}}table{{width:100%;min-width:840px;border-collapse:collapse}}th{{padding:10px 11px;text-align:left;color:#7890b2;font-size:10px;font-weight:600;letter-spacing:.04em;white-space:nowrap;background:rgba(4,13,25,.4)}}td{{padding:10px 11px;border-top:1px solid rgba(160,181,215,.09);color:#c8d6e9;font-size:12px;white-space:nowrap}}tr:hover td{{background:rgba(246,200,95,.045)}}.fn{{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.mono{{font-family:Consolas,"Noto Sans Mono CJK SC","WenQuanYi Micro Hei",monospace;font-size:11px}}.ok{{color:var(--green)}}.badtxt{{color:#ff9cab}}.status-tag{{display:inline-flex;padding:4px 7px;border-radius:5px;font-size:10px;font-weight:700}}.status-tag.done{{background:rgba(85,214,160,.12);color:#a7f3d0}}.status-tag.error{{background:rgba(251,113,133,.12);color:#fecdd3}}.status-tag.queued{{background:rgba(246,200,95,.12);color:#ffe7a4}}.status-tag.processing{{background:rgba(116,185,255,.12);color:#bfdbfe}}.table-action{{color:#9bc8ff;font-size:11px}}.table-action:hover{{color:#ffe7a4}}.actions{{display:flex;align-items:center;gap:10px}}.actions form{{margin:0}}.link-danger{{border:0;background:transparent;color:#ff9cab;padding:0;cursor:pointer;font-size:11px}}.link-danger:hover{{color:#fff}}
.control-grid{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,.8fr);gap:14px}}.control-form{{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}}.control-form label{{display:grid;gap:6px;color:#9eb1cb;font-size:11px}}.control-form input[type=number]{{width:100px;height:36px;border:1px solid var(--line);border-radius:7px;background:#081529;color:#edf4ff;padding:0 9px}}.control-form input[type=checkbox]{{accent-color:var(--gold)}}.primary-btn{{height:36px;padding:0 13px;border:1px solid rgba(246,200,95,.35);border-radius:7px;background:var(--gold-soft);color:#ffe7a4;cursor:pointer;font-size:12px}}.primary-btn:hover{{background:rgba(246,200,95,.2)}}.danger-btn{{height:36px;padding:0 13px;border:1px solid rgba(251,113,133,.3);border-radius:7px;background:rgba(251,113,133,.08);color:#fecdd3;cursor:pointer;font-size:12px}}
.empty-state{{padding:24px 10px;text-align:center;color:var(--muted);font-size:12px}}.pager{{display:flex;gap:12px;align-items:center;justify-content:flex-end;padding:12px 18px 16px;color:var(--muted);font-size:11px}}.pager a{{color:#9bc8ff}}.pager a.disabled{{pointer-events:none;color:#536985}}.hint{{color:var(--muted);font-size:11px;line-height:1.6}}
@media(max-width:1180px){{.metric-grid{{grid-template-columns:repeat(4,minmax(120px,1fr))}}}}
@media(max-width:900px){{.shell{{display:block}}.sidebar{{position:static;height:auto;padding:14px 18px;display:block;border-right:0;border-bottom:1px solid var(--line)}}.brand{{padding-bottom:12px;border-bottom:0}}.nav-label,.side-footer{{display:none}}.side-nav{{display:flex;overflow-x:auto;padding-top:8px;scrollbar-width:none}}.side-nav::-webkit-scrollbar{{display:none}}.side-nav a{{white-space:nowrap;padding:8px 10px}}.main{{padding:18px}}.work-grid,.control-grid{{grid-template-columns:1fr}}}}
@media(max-width:560px){{.main{{padding:14px}}.topbar{{align-items:flex-start;flex-direction:column}}.top-actions{{justify-content:flex-start}}h1{{font-size:21px}}.metric-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.metric .value{{font-size:21px}}.panel-head,.panel-body{{padding:14px}}.section{{margin-top:18px}}}}
</style></head>
<body>
<div class="shell">
<aside class="sidebar"><a class="brand" href="/"><span class="brand-mark">文</span><span><strong>公文智能排版</strong><small>管理员工作台</small></span></a>
<div class="nav-label">WORKSPACE</div><nav class="side-nav">
<a class="active" href="#overview"><span class="nav-index">01</span>总览</a><a href="#tasks"><span class="nav-index">02</span>任务中心</a><a href="#security"><span class="nav-index">03</span>安全与访问</a><a href="#runtime"><span class="nav-index">04</span>运行设置</a><a href="#logs"><span class="nav-index">05</span>日志查询</a>
</nav><div class="side-footer">当前服务<br><b>Python · 9527</b><br>数据目录受项目路径管理</div></aside>
<main class="main">
<header class="topbar"><div><div class="eyebrow">ADMIN WORKSPACE / {html.escape(str(version.get('version', '')))}</div><h1>运行总览</h1></div><div class="top-actions"><span class="service-pill {ready_class}"><i class="service-dot"></i>服务{ready_state}</span><button class="top-button" type="button" onclick="window.location.reload()">刷新</button><a class="top-link" href="/">返回工具</a><a class="top-link" href="/stats" target="_blank">JSON</a><form method="post" action="/admin/logout">{csrf_input}<button class="top-button" type="submit">退出</button></form></div></header>
{('<div class="alert"><strong>运行检查</strong><span>数据库、输出目录或日志目录存在异常，请先检查运行环境，再处理任务。</span></div>') if not ready.get('ok') else ''}
<section id="overview" class="section"><div class="section-heading"><div><h2>关键指标</h2><p>排版服务当前累计运行数据</p></div><span class="section-meta">自动刷新 · 15 秒</span></div><div class="metric-grid">
<div class="metric"><div class="value">{stats.get('total',0)}</div><div class="label">总任务</div></div><div class="metric good"><div class="value">{stats.get('done',0)}</div><div class="label">成功任务</div></div><div class="metric bad"><div class="value">{stats.get('error',0)}</div><div class="label">失败任务</div></div><div class="metric good"><div class="value">{stats.get('rate',0)}%</div><div class="label">成功率</div></div><div class="metric"><div class="value">{version.get('queued',0)}</div><div class="label">当前排队</div></div><div class="metric"><div class="value">{version.get('processing',0)}</div><div class="label">当前处理</div></div><div class="metric"><div class="value">{stats.get('avg_s',0)}s</div><div class="label">平均耗时</div></div><div class="metric"><div class="value">{stats.get('unique_ips',0)}</div><div class="label">独立 IP</div></div>
</div></section>
<section class="section"><div class="work-grid"><div class="panel"><div class="panel-head"><div><h3>任务趋势</h3><p>按日期统计成功与失败任务</p></div><span class="section-meta">最近 {len(trend[-14:])} 个记录日</span></div><div class="panel-body"><div class="trend">{trend_bars}</div><div class="legend"><span><i class="done"></i>成功</span><span><i class="error"></i>失败</span></div></div></div><div class="panel"><div class="panel-head"><div><h3>运行状态</h3><p>服务依赖和处理队列</p></div><span class="service-pill {ready_class}">{ready_state}</span></div><div class="panel-body"><ul class="health-list">{check_items}</ul><div class="runtime-grid"><div class="runtime-item"><b>{version.get('max_workers',0)}</b><span>工作线程</span></div><div class="runtime-item"><b>{version.get('max_queue',0)}</b><span>队列上限</span></div><div class="runtime-item"><b>{version.get('max_upload_mb',0)} MB</b><span>单文件上限</span></div><div class="runtime-item"><b>{version.get('process_timeout_seconds',0)}s</b><span>处理超时</span></div></div></div></div></div></section>
<section id="tasks" class="section"><div class="section-heading"><div><h2>任务中心</h2><p>优先处理失败任务，点击日志查看完整排版过程</p></div><span class="section-meta">{len(stats.get('recent',[]))} / {stats.get('recent_total',0)} 条</span></div><div class="panel"><div class="table-wrap"><table><thead><tr><th>时间</th><th>文件名</th><th>来源 IP</th><th>大小</th><th>类型</th><th>段数</th><th>耗时</th><th>状态</th><th>操作</th></tr></thead><tbody>{"".join(rows) or '<tr><td colspan="9"><div class="empty-state">暂无任务，用户上传 DOCX 后将在此显示。</div></td></tr>'}</tbody></table></div>{recent_pager}</div></section>
<section id="security" class="section"><div class="section-heading"><div><h2>安全与访问</h2><p>查看访问活跃度并处理异常来源</p></div><span class="section-meta">{stats.get('ip_total',0)} 个活跃 IP · {len(stats.get('banned_ips',[]))} 个封禁</span></div><div class="work-grid"><div class="panel"><div class="panel-head"><div><h3>活跃 IP</h3><p>按最近访问时间排序</p></div></div><div class="table-wrap"><table><thead><tr><th>IP</th><th>上传</th><th>成功</th><th>失败</th><th>最近活跃</th><th>最近文件</th><th>操作</th></tr></thead><tbody>{ips or '<tr><td colspan="7"><div class="empty-state">暂无访问记录。</div></td></tr>'}</tbody></table></div>{ip_pager}</div><div class="panel"><div class="panel-head"><div><h3>封禁 IP</h3><p>危险操作需要管理员确认</p></div></div><div class="table-wrap"><table><thead><tr><th>IP</th><th>原因</th><th>时间</th><th>操作</th></tr></thead><tbody>{banned_rows or '<tr><td colspan="4"><div class="empty-state">暂无封禁 IP。</div></td></tr>'}</tbody></table></div></div></div></section>
<section id="runtime" class="section"><div class="section-heading"><div><h2>运行设置</h2><p>调整访问限额、列表密度和永久保存策略</p></div><span class="section-meta">限额{limit_state}</span></div><div class="control-grid"><div class="panel"><div class="panel-head"><div><h3>上传限额</h3><p>同一 IP 在指定时间窗口内的排版次数限制</p></div></div><div class="panel-body"><form class="control-form" method="post" action="/limit">{csrf_input}<label><span>状态</span><span><input type="checkbox" name="enabled" value="1"{limit_checked}> 启用</span></label><label><span>时间窗口（秒）</span><input type="number" min="1" name="window_seconds" value="{limit['window_seconds']}"></label><label><span>允许次数</span><input type="number" min="1" name="count" value="{limit['count']}"></label><button class="primary-btn" type="submit">保存设置</button></form></div></div><div class="panel"><div class="panel-head"><div><h3>文件保存</h3><p>已接收原件、排版结果、任务日志和任务记录永久保留</p></div></div><div class="panel-body"><p class="hint">系统不按时间自动删除用户文件。请结合服务器磁盘空间自行制定归档与备份策略。</p></div></div></div><div class="panel" style="margin-top:14px"><div class="panel-head"><div><h3>显示设置</h3><p>控制任务中心和活跃 IP 每页显示数量</p></div></div><div class="panel-body"><form class="control-form" method="get" action="/monitor"><label><span>最近任务/页</span><input type="number" min="1" max="{max_monitor_page_size}" name="recent_size" value="{query['recent_size']}"></label><label><span>活跃 IP/页</span><input type="number" min="1" max="{max_monitor_page_size}" name="ip_size" value="{query['ip_size']}"></label><button class="primary-btn" type="submit">应用</button><a class="top-link" href="/monitor">恢复默认</a><span class="hint">默认每页 50 条，最多 {max_monitor_page_size} 条。</span></form></div></div></section>
<section id="logs" class="section"><div class="panel"><div class="panel-head"><div><h3>日志查询</h3><p>从任务中心的“查看日志”进入具体任务日志</p></div><a class="top-link" href="/stats" target="_blank">打开 JSON API</a></div><div class="panel-body"><p class="hint">日志仅保存在服务端运行目录，页面不会显示 Cookie、管理员密钥或代理密钥。失败任务优先从任务中心进入排查。</p></div></div></section>
<footer class="side-footer" style="margin-top:24px">最后生成：{html_escape(now_local()[:19])} · 页面每 15 秒自动刷新</footer>
</main></div>
<script>
setInterval(() => {{
  if (document.hidden) return;
  const active = document.activeElement;
  if (active && ['INPUT', 'SELECT', 'TEXTAREA'].includes(active.tagName)) return;
  window.location.reload();
}}, 15000);
</script>
</body></html>"""
