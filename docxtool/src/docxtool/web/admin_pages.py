"""管理员页面 HTML 渲染辅助。

本模块只负责生成管理员页面 HTML，不读取请求体、不校验密钥，也不访问任务或 DOCX。
"""

from __future__ import annotations


def render_admin_login_html() -> str:
    """无需传入数据，返回管理员登录页 HTML 字符串。"""
    return """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>管理员登录 · 公文智能排版</title>
<style>
:root{--bg:#07101f;--panel:#0d1a2e;--line:rgba(160,181,215,.18);--text:#edf4ff;--muted:#8fa2be;--gold:#f6c85f}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;font-family:"Microsoft YaHei","Noto Sans CJK SC","PingFang SC",sans-serif;background:radial-gradient(circle at 25% 20%,rgba(66,100,150,.16),transparent 32%),var(--bg);color:var(--text)}
.workspace{width:min(920px,100%);display:grid;grid-template-columns:minmax(0,1.05fr) minmax(340px,.75fr);border:1px solid var(--line);border-radius:14px;overflow:hidden;background:rgba(7,16,31,.86);box-shadow:0 28px 80px rgba(0,0,0,.35)}
.intro{padding:52px 48px;background:linear-gradient(145deg,rgba(18,36,61,.94),rgba(9,23,40,.94));border-right:1px solid var(--line)}.mark{width:46px;height:46px;display:grid;place-items:center;border-radius:11px;background:linear-gradient(135deg,#f6c85f,#e89c3a);color:#152238;font-size:22px;font-weight:900;margin-bottom:28px}.eyebrow{color:var(--gold);font-size:11px;letter-spacing:.13em;margin-bottom:10px}h1{font-size:29px;margin:0 0 13px}.intro p{max-width:38ch;color:#a9bad1;line-height:1.8;font-size:14px;margin:0}.status{display:grid;gap:10px;margin-top:34px}.status span{display:flex;align-items:center;gap:9px;color:#8fa2be;font-size:12px}.status i{width:7px;height:7px;border-radius:50%;background:#55d6a0}
.login{padding:48px 40px;background:rgba(9,21,37,.92);display:flex;flex-direction:column;justify-content:center}.login h2{font-size:18px;margin:0 0 6px}.login>p{color:var(--muted);font-size:12px;line-height:1.7;margin:0 0 24px}label{display:block;color:#b9c9df;font-size:12px;font-weight:700;margin-bottom:8px}input{width:100%;height:44px;border:1px solid var(--line);border-radius:8px;background:#071426;color:#fff;padding:0 12px;font-size:14px;outline:none}input:focus{border-color:rgba(246,200,95,.5);box-shadow:0 0 0 4px rgba(246,200,95,.08)}button{width:100%;height:44px;margin-top:15px;border:1px solid rgba(246,200,95,.42);border-radius:8px;background:rgba(246,200,95,.14);color:#ffe7a4;font-weight:800;cursor:pointer}button:hover{background:rgba(246,200,95,.22)}.hint{font-size:11px;color:#6f85a4;margin-top:14px;line-height:1.65}.back{display:inline-block;color:#9bc8ff;font-size:11px;margin-top:18px;text-decoration:none}
@media(max-width:760px){.workspace{grid-template-columns:1fr}.intro{padding:30px;border-right:0;border-bottom:1px solid var(--line)}.intro p,.status{display:none}.mark{margin-bottom:18px}.login{padding:30px}}
</style></head>
<body><main class="workspace"><section class="intro"><div class="mark">文</div><div class="eyebrow">DOCXTOOL ADMIN</div><h1>公文排版工作台</h1><p>集中查看任务状态、运行指标、访问安全和服务配置。管理员会话通过安全 Cookie 建立。</p><div class="status"><span><i></i>后端服务已连接</span><span><i></i>管理员会话受保护</span></div></section><section class="login"><h2>管理员登录</h2><p>输入服务器配置的管理员密钥，登录后进入运行工作台。</p><form method="post" action="/admin/login"><label for="admin_token">管理员密钥</label><input id="admin_token" name="admin_token" type="password" autocomplete="current-password" required autofocus><button type="submit">进入工作台</button></form><div class="hint">密钥仅用于建立当前管理员会话，不会写入页面地址。</div><a class="back" href="/">返回公文排版工具</a></section></main></body></html>"""
