from __future__ import annotations

from docxtool.web.preset_route_handlers import (
    handle_preset_create,
    handle_preset_delete,
    handle_preset_detail,
    handle_preset_update,
    handle_presets_list,
)


class FakeHandler:
    """测试用 handler，保存请求属性和响应调用。"""

    def __init__(self) -> None:
        self.headers = {"Cookie": "owner=1"}
        self.client_address = ("127.0.0.1", 12345)
        self._request_params_cache = {
            "id": "tpl",
            "name": "模板",
            "description": "说明",
            "config_json": {"schema_version": 1},
        }
        self._preset_owner_id = "owner-1"
        self._preset_cookie_header = "owner=1; Path=/"
        self._preset_public_only = False
        self._preset_admin = False
        self.responses: list[tuple[str, object]] = []

    def _json(self, obj: dict, status: int = 200, extra_headers=None) -> None:
        """传入 JSON 对象、状态码和可选头，记录 JSON 响应。"""
        self.responses.append(("json", (obj, status, extra_headers)))

    def _json_error(self, code: str, message: str, status: int) -> None:
        """传入错误码、提示和状态码，记录 JSON 错误响应。"""
        self.responses.append(("json_error", (code, message, status)))

    def _json_error_fields(self, error: tuple[str, str, int]) -> None:
        """传入错误字段元组，记录 JSON 错误字段响应。"""
        self.responses.append(("json_error_fields", error))


def _principal(_headers, _client_address) -> dict:
    """传入请求头和客户端地址，返回测试 principal。"""
    return {"owner_id": "owner-1", "cookie": "owner-cookie"}


def _optional_cookie(value: str):
    """传入 cookie 字符串，返回测试 Set-Cookie 头或 None。"""
    return [("Set-Cookie", value)] if value else None


def _preset_error(exc: ValueError, *, not_found_status: int = 404) -> tuple[str, str, int]:
    """传入 ValueError，返回测试用稳定错误字段。"""
    code, message = str(exc).split(":", 1)
    return code, message.strip(), not_found_status if code == "TEMPLATE_NOT_FOUND" else 400


def test_handle_presets_list_uses_owner_and_cookie() -> None:
    """preset 列表处理器应按 principal owner 查询并返回 owner cookie。"""
    handler = FakeHandler()

    handle_presets_list(
        handler,
        principal=_principal,
        list_presets=lambda owner_id: [{"owner": owner_id}],
        optional_set_cookie_headers=_optional_cookie,
    )

    assert handler.responses == [
        ("json", ({"presets": [{"owner": "owner-1"}]}, 200, [("Set-Cookie", "owner-cookie")]))
    ]


def test_handle_preset_detail_validates_id_and_missing_template() -> None:
    """preset 详情处理器应拒绝空 ID，并在未找到模板时返回 404。"""
    empty = FakeHandler()
    missing = FakeHandler()

    handle_preset_detail(
        empty,
        "",
        principal=_principal,
        get_preset=lambda *_args, **_kwargs: {},
        optional_set_cookie_headers=_optional_cookie,
    )
    handle_preset_detail(
        missing,
        "tpl",
        principal=_principal,
        get_preset=lambda *_args, **_kwargs: {},
        optional_set_cookie_headers=_optional_cookie,
    )

    assert empty.responses == [("json_error", ("TEMPLATE_ID_INVALID", "无效的模板 ID", 400))]
    assert missing.responses == [("json_error", ("TEMPLATE_NOT_FOUND", "模板不存在", 404))]


def test_handle_preset_detail_returns_existing_template() -> None:
    """preset 详情处理器应返回查询到的模板和 owner cookie。"""
    handler = FakeHandler()

    handle_preset_detail(
        handler,
        "tpl",
        principal=_principal,
        get_preset=lambda preset_id, owner_id: {"id": preset_id, "owner": owner_id},
        optional_set_cookie_headers=_optional_cookie,
    )

    assert handler.responses == [
        ("json", ({"id": "tpl", "owner": "owner-1"}, 200, [("Set-Cookie", "owner-cookie")]))
    ]


def test_handle_preset_create_update_and_delete_call_store_functions() -> None:
    """preset 创建、更新和删除处理器应传递缓存参数、owner 和可见性字段。"""
    handler = FakeHandler()
    calls: list[tuple[str, object]] = []

    handle_preset_create(
        handler,
        insert_preset=lambda name, desc, config, **kw: calls.append(("create", (name, desc, config, kw))) or {"id": kw["preset_id"]},
        preset_error_from_exception=_preset_error,
        optional_set_cookie_headers=_optional_cookie,
    )
    handle_preset_update(
        handler,
        "tpl",
        update_preset=lambda preset_id, name, desc, config, **kw: calls.append(("update", (preset_id, name, desc, config, kw))) or {"id": preset_id},
        preset_error_from_exception=_preset_error,
        optional_set_cookie_headers=_optional_cookie,
    )
    handle_preset_delete(
        handler,
        "tpl",
        delete_preset=lambda preset_id, **kw: calls.append(("delete", (preset_id, kw))) or {"deleted": preset_id},
        preset_error_from_exception=_preset_error,
        optional_set_cookie_headers=_optional_cookie,
    )

    assert calls[0][0] == "create"
    assert calls[0][1][3]["owner_id"] == "owner-1"
    assert calls[0][1][3]["visibility"] == "private"
    assert calls[1][0] == "update"
    assert calls[1][1][4]["public_only"] is False
    assert calls[2] == ("delete", ("tpl", {"owner_id": "owner-1", "public_only": False}))
    assert [response[1][1] for response in handler.responses] == [201, 200, 200]


def test_handle_preset_create_reports_store_error() -> None:
    """preset 创建处理器应把 store ValueError 转成稳定错误字段。"""
    handler = FakeHandler()

    handle_preset_create(
        handler,
        insert_preset=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("TEMPLATE_NAME_REQUIRED: 模板名称不能为空")),
        preset_error_from_exception=_preset_error,
        optional_set_cookie_headers=_optional_cookie,
    )

    assert handler.responses == [("json_error_fields", ("TEMPLATE_NAME_REQUIRED", "模板名称不能为空", 400))]
