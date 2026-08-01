from __future__ import annotations

from docxtool.web.page_route_handlers import handle_admin_login_page, handle_frontend_index


class FakeHandler:
    """测试用 handler，记录页面响应或错误状态。"""

    def __init__(self) -> None:
        self.text_calls: list[tuple[str, str]] = []
        self.errors: list[int] = []

    def _text(self, body: str, mime: str) -> None:
        """传入正文和 MIME，记录文本响应并返回 None。"""
        self.text_calls.append((body, mime))

    def send_error(self, status: int) -> None:
        """传入 HTTP 状态码，记录错误响应并返回 None。"""
        self.errors.append(status)


def test_handle_frontend_index_sends_html_when_present() -> None:
    """首页存在时，页面路由处理器应发送 text/html 响应。"""
    handler = FakeHandler()

    handle_frontend_index(handler, load_index_html=lambda: "<html>ok</html>")

    assert handler.text_calls == [("<html>ok</html>", "text/html")]
    assert handler.errors == []


def test_handle_frontend_index_returns_404_when_missing() -> None:
    """首页缺失时，页面路由处理器应保持旧行为返回 404。"""
    handler = FakeHandler()

    handle_frontend_index(handler, load_index_html=lambda: None)

    assert handler.text_calls == []
    assert handler.errors == [404]


def test_handle_admin_login_page_sends_rendered_html() -> None:
    """管理员登录页处理器应发送渲染回调返回的 HTML。"""
    handler = FakeHandler()

    handle_admin_login_page(handler, render_login_html=lambda: "<form></form>")

    assert handler.text_calls == [("<form></form>", "text/html")]
