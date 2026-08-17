from copy import deepcopy
import http.client
import json
import threading

import pytest

from apps.wps import account_store
from apps.wps.format_profile_store import FormatProfileError, FormatProfileStore
from apps.wps.control.server import WpsControlApplication, create_server
from docxtool.wps_server.format_config import load_active_format_profile


def _config() -> dict:
    return deepcopy(load_active_format_profile()["format_config"])


def test_system_default_profile_makes_heading3_bold():
    styles = load_active_format_profile()["format_config"]["styles"]
    heading3 = next(style for style in styles if style["name"] == "三级标题")

    assert heading3["bold"] is True


def test_profiles_are_isolated_by_account_and_restore_after_relogin(tmp_path):
    store = FormatProfileStore(tmp_path / "format_profiles.db")
    first = store.create("wusr_a", "机关模板", _config())
    second = store.create("wusr_b", "机关模板", _config())

    assert [item["profile_id"] for item in store.list_profiles("wusr_a")] == [
        first["profile_id"]
    ]
    assert [item["profile_id"] for item in store.list_profiles("wusr_b")] == [
        second["profile_id"]
    ]
    assert store.active_profile("wusr_a")["profile_id"] == first["profile_id"]

    reopened = FormatProfileStore(tmp_path / "format_profiles.db")
    assert reopened.active_profile("wusr_a")["name"] == "机关模板"


def test_profile_name_and_content_can_be_updated_atomically(tmp_path):
    store = FormatProfileStore(tmp_path / "format_profiles.db")
    created = store.create("wusr_a", "旧名称", _config())
    updated_config = _config()
    updated_config["page"]["margin_left_cm"] = 3.2

    updated = store.update(
        "wusr_a", created["profile_id"], "新名称", updated_config
    )

    assert updated["name"] == "新名称"
    assert updated["revision"] == 2
    assert updated["format_config"]["page"]["margin_left_cm"] == 3.2
    assert store.active_profile("wusr_a")["profile_id"] == created["profile_id"]


def test_duplicate_name_is_rejected_without_overwriting_existing_profile(tmp_path):
    store = FormatProfileStore(tmp_path / "format_profiles.db")
    first = store.create("wusr_a", "模板 A", _config())
    second = store.create("wusr_a", "模板 B", _config())

    with pytest.raises(FormatProfileError, match="WPS_FORMAT_PROFILE_NAME_CONFLICT"):
        store.update("wusr_a", second["profile_id"], "模板   A", _config())

    assert store.get("wusr_a", first["profile_id"])["name"] == "模板 A"
    assert store.get("wusr_a", second["profile_id"])["name"] == "模板 B"


def test_deleting_active_profile_switches_to_system_default(tmp_path):
    store = FormatProfileStore(tmp_path / "format_profiles.db")
    created = store.create("wusr_a", "待删除", _config())

    result = store.delete("wusr_a", created["profile_id"])

    assert result == {"deleted": True, "active_profile_id": ""}
    assert store.active_profile("wusr_a") is None


def test_legacy_config_is_imported_once_for_the_first_account(tmp_path):
    store = FormatProfileStore(tmp_path / "format_profiles.db")
    legacy = _config()
    legacy["page"]["margin_right_cm"] = 3.1

    first = store.initialize("wusr_a", legacy)
    second = store.initialize("wusr_a", _config())

    assert first["legacy_imported"] is True
    assert first["active_profile"]["name"] == "我的格式"
    assert first["active_profile"]["format_config"]["page"]["margin_right_cm"] == 3.1
    assert second["legacy_imported"] is False
    assert len(store.list_profiles("wusr_a")) == 1


def test_account_clear_does_not_delete_format_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    store = FormatProfileStore()
    created = store.create("wusr_a", "保留模板", _config())

    assert account_store.clear_account() == 0
    assert store.get("wusr_a", created["profile_id"])["name"] == "保留模板"


def test_invalid_names_and_cross_account_profile_ids_fail(tmp_path):
    store = FormatProfileStore(tmp_path / "format_profiles.db")
    created = store.create("wusr_a", "模板", _config())

    with pytest.raises(FormatProfileError, match="WPS_FORMAT_PROFILE_NAME_REQUIRED"):
        store.create("wusr_a", "  ", _config())
    with pytest.raises(FormatProfileError, match="WPS_FORMAT_PROFILE_NOT_FOUND"):
        store.get("wusr_b", created["profile_id"])


class _AccountRuntime:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    def summary(self) -> dict:
        return {"user_id": self.user_id}


def test_control_application_binds_profile_owner_to_account_runtime(tmp_path):
    store = FormatProfileStore(tmp_path / "format_profiles.db")
    first = WpsControlApplication(
        tmp_path, "token", _AccountRuntime("wusr_a"), format_profile_store=store
    )
    second = WpsControlApplication(
        tmp_path, "token", _AccountRuntime("wusr_b"), format_profile_store=store
    )

    created = first.format_profiles_create(
        {"name": "账号甲模板", "format_config": _config()}
    )["saved_profile"]

    assert first.format_profiles_active()["active_profile_id"] == created["profile_id"]
    assert second.format_profiles_active()["active_profile_id"] == "system:default"
    with pytest.raises(FormatProfileError, match="WPS_FORMAT_PROFILE_NOT_FOUND"):
        second.format_profiles_detail(created["profile_id"])


def test_control_application_protects_system_profile_and_requires_account(tmp_path):
    store = FormatProfileStore(tmp_path / "format_profiles.db")
    signed_in = WpsControlApplication(
        tmp_path, "token", _AccountRuntime("wusr_a"), format_profile_store=store
    )
    missing = WpsControlApplication(
        tmp_path, "token", format_profile_store=store
    )

    with pytest.raises(FormatProfileError, match="WPS_FORMAT_PROFILE_SYSTEM_LOCKED"):
        signed_in.format_profiles_delete({"profile_id": "system:default"})
    with pytest.raises(FormatProfileError, match="WPS_FORMAT_PROFILE_ACCOUNT_REQUIRED"):
        missing.format_profiles_list()


def test_control_http_routes_create_and_read_local_profiles(tmp_path):
    store = FormatProfileStore(tmp_path / "format_profiles.db")
    server = create_server(
        tmp_path,
        "token",
        0,
        account_runtime=_AccountRuntime("wusr_a"),
        format_profile_store=store,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    headers = {"Authorization": "Bearer token", "Content-Type": "application/json"}
    try:
        connection.request(
            "POST",
            "/v1/format/profiles/create",
            body=json.dumps({"name": "本机模板", "format_config": _config()}),
            headers=headers,
        )
        created = json.loads(connection.getresponse().read())
        assert created["ok"] is True
        assert created["data"]["saved_profile"]["name"] == "本机模板"

        connection.request("GET", "/v1/format/profiles/active", headers=headers)
        active = json.loads(connection.getresponse().read())
        assert active["ok"] is True
        assert active["data"]["active_profile"]["name"] == "本机模板"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
