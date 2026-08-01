"""管理员表单请求体解析辅助。

本模块只从已读取的表单字节中解析字段，不校验管理员密钥、不创建 session。
"""

from __future__ import annotations

from urllib.parse import parse_qs


def parse_admin_login_token(body: bytes) -> str:
    """传入管理员登录表单请求体 bytes，返回去除空白后的 token 字符串。"""
    params = parse_form_body(body)
    return str(params.get("admin_token") or params.get("token") or "").strip()


def parse_form_body(body: bytes) -> dict[str, str]:
    """传入 URL 编码表单 bytes，返回字段到最后一个值的字典；解析失败返回空字典。"""
    if not body:
        return {}
    try:
        parsed = parse_qs(body.decode("utf-8"))
    except Exception:
        return {}
    return {key: (values[-1] if isinstance(values, list) and values else values) for key, values in parsed.items()}
