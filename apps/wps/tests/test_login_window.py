import pytest

from apps.wps.login_window import (
    password_mask,
    required_window_height,
    submit_account,
    window_geometry,
)
from apps.wps.public_api import PublicApiError


class _Api:
    origin = "http://127.0.0.1:9527"

    def __init__(self):
        self.calls = []

    @staticmethod
    def _response(payload):
        return {
            "user": {
                "id": "wusr_1",
                "username": payload["username"],
                "status": "active",
            },
            "device": {"id": "wdev_1"},
            "session_token": "session-token-001",
            "session_expires_at": 86400,
        }

    def login(self, payload):
        self.calls.append(("login", payload))
        return self._response(payload)

    def register(self, payload):
        self.calls.append(("register", payload))
        return self._response(payload)


class _Store:
    def __init__(self):
        self.saved = []

    def save_account(self, account):
        self.saved.append(dict(account))


def test_login_submission_calls_only_login_and_saves_the_account():
    api = _Api()
    store = _Store()

    account = submit_account(
        mode="login",
        username="User01",
        password="Pass01",
        confirmation="",
        api=api,
        account_store=store,
        device_key="device-key-001",
    )

    assert [name for name, _payload in api.calls] == ["login"]
    assert set(api.calls[0][1]) == {"username", "password", "device"}
    assert account["username"] == "User01"
    assert "display_name" not in account
    assert store.saved == [account]


def test_registration_calls_only_register_without_a_display_name():
    api = _Api()
    store = _Store()

    account = submit_account(
        mode="register",
        username="User01",
        password="Pass01",
        confirmation="Pass01",
        api=api,
        account_store=store,
        device_key="device-key-001",
    )

    assert [name for name, _payload in api.calls] == ["register"]
    assert set(api.calls[0][1]) == {"username", "password", "device"}
    assert account["username"] == "User01"
    assert store.saved == [account]


def test_registration_password_mismatch_stops_before_the_api_call():
    api = _Api()
    store = _Store()

    with pytest.raises(ValueError, match="两次输入的密码不一致"):
        submit_account(
            mode="register",
            username="User01",
            password="Pass01",
            confirmation="Pass02",
            api=api,
            account_store=store,
            device_key="device-key-001",
        )

    assert api.calls == []
    assert store.saved == []


def test_account_service_failure_does_not_save_an_account():
    class FailingApi(_Api):
        def login(self, payload):
            self.calls.append(("login", payload))
            raise PublicApiError("INVALID_CREDENTIALS", "账号或密码错误", 401)

    api = FailingApi()
    store = _Store()

    with pytest.raises(PublicApiError, match="INVALID_CREDENTIALS"):
        submit_account(
            mode="login",
            username="User01",
            password="Pass01",
            confirmation="",
            api=api,
            account_store=store,
            device_key="device-key-001",
        )

    assert [name for name, _payload in api.calls] == ["login"]
    assert store.saved == []


def test_window_geometry_keeps_requested_height_and_centers_the_window():
    assert window_geometry(420, 536, 1920, 1080) == "420x536+750+272"
    assert window_geometry(420, 536, 360, 480) == "420x536+0+0"


def test_required_window_height_includes_visible_form_and_bottom_padding():
    assert required_window_height(136, 356, 34) == 526


def test_password_mask_tracks_eye_button_visibility():
    assert password_mask(False) == "*"
    assert password_mask(True) == ""
