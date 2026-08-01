from __future__ import annotations

from docxtool.web.health_route_handlers import handle_health, handle_ready, handle_version


class FakeHandler:
    """测试用 handler，记录 JSON 响应体和状态码。"""

    def __init__(self) -> None:
        self.json_calls: list[tuple[dict[str, object], int]] = []

    def _json(self, payload: dict[str, object], status: int = 200) -> None:
        """传入 JSON payload 和状态码，记录响应并返回 None。"""
        self.json_calls.append((payload, status))


def test_handle_health_sends_public_payload() -> None:
    """健康检查处理器应原样发送 payload 回调结果。"""
    handler = FakeHandler()

    handle_health(handler, health_payload=lambda: {"ok": True})

    assert handler.json_calls == [({"ok": True}, 200)]


def test_handle_ready_uses_200_when_ready() -> None:
    """readiness 为 ok 时，应发送 200。"""
    handler = FakeHandler()

    handle_ready(handler, ready_payload=lambda: {"ok": True, "checks": {"database": True}})

    assert handler.json_calls == [({"ok": True, "checks": {"database": True}}, 200)]


def test_handle_ready_uses_503_when_not_ready() -> None:
    """readiness 非 ok 时，应保持旧行为发送 503。"""
    handler = FakeHandler()

    handle_ready(handler, ready_payload=lambda: {"ok": False, "checks": {"database": False}})

    assert handler.json_calls == [({"ok": False, "checks": {"database": False}}, 503)]


def test_handle_version_sends_version_payload() -> None:
    """版本处理器应原样发送版本 payload。"""
    handler = FakeHandler()

    handle_version(handler, version_payload=lambda: {"version": "2.3"})

    assert handler.json_calls == [({"version": "2.3"}, 200)]
