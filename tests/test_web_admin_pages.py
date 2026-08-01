from __future__ import annotations

from docxtool.web.admin_pages import render_admin_login_html


def test_render_admin_login_html_preserves_form_contract() -> None:
    """管理员页面模块无需传参，应返回包含登录表单契约的 HTML。"""
    html = render_admin_login_html()

    assert html.startswith("<!doctype html>")
    assert '<form method="post" action="/admin/login">' in html
    assert 'name="admin_token"' in html
    assert 'type="password"' in html
    assert 'autocomplete="current-password"' in html
    assert "公文排版工作台" in html


def test_render_admin_login_html_does_not_embed_secret_or_legacy_token() -> None:
    """管理员页面模块返回的 HTML 不应包含真实密钥字段值或 URL token。"""
    html = render_admin_login_html()

    assert "ADMIN_TOKEN=" not in html
    assert "PROXY_SECRET=" not in html
    assert "?token=" not in html
