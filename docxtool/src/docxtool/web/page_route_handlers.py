"""静态页面路由处理辅助。

本模块只负责把已经生成或读取到的页面内容写入 HTTP handler，不读取数据库、不处理
任务队列，也不触碰 DOCX 识别和渲染链路。
"""

from __future__ import annotations

from collections.abc import Callable


def handle_frontend_index(handler, *, load_index_html: Callable[[], str | None]) -> None:
    """传入 HTTP handler 和首页读取回调，发送首页 HTML；缺失时返回 404。"""
    body = load_index_html()
    if body is None:
        handler.send_error(404)
        return
    handler._text(body, "text/html")


def handle_admin_login_page(handler, *, render_login_html: Callable[[], str]) -> None:
    """传入 HTTP handler 和登录页渲染回调，发送管理员登录 HTML。"""
    handler._text(render_login_html(), "text/html")
