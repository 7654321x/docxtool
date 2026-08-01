from __future__ import annotations

from types import SimpleNamespace

from docxtool.web.protected_route_handlers import (
    handle_admin_post_route,
    handle_admin_resource_route,
    handle_admin_route,
    handle_file_api_resource_route,
    handle_file_api_route,
    handle_preset_mutation_route,
    handle_preset_resource_mutation_route,
)


def test_handle_admin_route_runs_action_only_when_authorized() -> None:
    """管理员 GET 保护器应在鉴权失败时跳过动作，成功时传入 parsed。"""
    parsed = SimpleNamespace(path="/monitor/ip")
    calls: list[object] = []

    handle_admin_route(parsed, require_admin=lambda _parsed: False, action=calls.append)
    handle_admin_route(parsed, require_admin=lambda _parsed: True, action=calls.append)

    assert calls == [parsed]


def test_handle_admin_resource_route_passes_resource_after_auth() -> None:
    """管理员资源保护器应在鉴权通过后把资源 ID 传给动作。"""
    calls: list[str] = []

    handle_admin_resource_route(
        SimpleNamespace(path="/log/task-1"),
        "task-1",
        require_admin=lambda _parsed: True,
        action=calls.append,
    )

    assert calls == ["task-1"]


def test_handle_admin_post_route_requires_post_auth() -> None:
    """管理员 POST 保护器应使用 POST 鉴权回调控制写操作。"""
    parsed = SimpleNamespace(path="/monitor/ban")
    calls: list[object] = []

    handle_admin_post_route(parsed, require_admin_post=lambda _parsed: False, action=calls.append)
    handle_admin_post_route(parsed, require_admin_post=lambda _parsed: True, action=calls.append)

    assert calls == [parsed]


def test_handle_file_api_route_runs_action_only_when_authorized() -> None:
    """文件 API 保护器应在代理鉴权成功后执行无参动作。"""
    calls: list[str] = []

    handle_file_api_route(require_file_api=lambda: False, action=lambda: calls.append("bad"))
    handle_file_api_route(require_file_api=lambda: True, action=lambda: calls.append("ok"))

    assert calls == ["ok"]


def test_handle_file_api_resource_route_passes_resource_id() -> None:
    """文件 API 资源保护器应在鉴权成功后传入任务或文件 ID。"""
    calls: list[str] = []

    handle_file_api_resource_route("task-1", require_file_api=lambda: True, action=calls.append)

    assert calls == ["task-1"]


def test_handle_preset_mutation_route_requires_mutation_auth() -> None:
    """模板创建保护器应在模板修改鉴权成功后执行创建动作。"""
    calls: list[str] = []

    handle_preset_mutation_route(
        SimpleNamespace(path="/api/presets"),
        require_preset_mutation=lambda _parsed: False,
        action=lambda: calls.append("bad"),
    )
    handle_preset_mutation_route(
        SimpleNamespace(path="/api/presets"),
        require_preset_mutation=lambda _parsed: True,
        action=lambda: calls.append("ok"),
    )

    assert calls == ["ok"]


def test_handle_preset_resource_mutation_route_passes_preset_id() -> None:
    """模板资源保护器应在鉴权成功后把模板 ID 传给更新或删除动作。"""
    calls: list[str] = []

    handle_preset_resource_mutation_route(
        SimpleNamespace(path="/api/presets/p1"),
        "p1",
        require_preset_mutation=lambda _parsed: True,
        action=calls.append,
    )

    assert calls == ["p1"]
