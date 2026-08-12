import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide2.QtCore import Qt
from PySide2.QtGui import QIcon, QPixmap
from PySide2.QtWidgets import QApplication, QLineEdit

from apps.wps import desktop_runtime
from apps.wps.login_window import (
    AuthenticationWorker,
    LoginDialog,
    PreferencesDialog,
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

    @staticmethod
    def new_device_key():
        return "new-device-key"


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
        remember_password=True,
        auto_login=True,
    )

    assert [name for name, _payload in api.calls] == ["login"]
    assert set(api.calls[0][1]) == {"username", "password", "device"}
    assert account["username"] == "User01"
    assert "display_name" not in account
    assert store.saved == [account]
    assert account["remember_password"] is True
    assert account["auto_login"] is True


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
        remember_password=False,
        auto_login=False,
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


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_dialog_prefills_account_password_and_preferences(qt_app):
    dialog = LoginDialog(
        api=_Api(),
        account_store=_Store(),
        initial_username="User01",
        initial_password="Pass01",
        device_key="device-key-001",
        remember_password=True,
        auto_login=True,
    )

    assert dialog.username_input.text() == "User01"
    assert dialog.password_input.text() == "Pass01"
    assert dialog.remember_checkbox.isChecked() is True
    assert dialog.auto_checkbox.isChecked() is True
    assert dialog.startup_checkbox.isChecked() is False
    assert dialog.windowIcon().isNull() is False
    assert dialog.status_label.isVisible() is False
    assert dialog.password_input.width() == dialog.username_input.width()


def test_login_dialog_uses_custom_title_bar_and_d_icon(qt_app):
    dialog = LoginDialog(api=_Api(), account_store=_Store())

    assert dialog.windowFlags() & Qt.FramelessWindowHint
    assert dialog.title_bar.icon_label.pixmap().isNull() is False
    assert dialog.title_bar.title_label.text() == "DocxTool WPS"
    assert dialog.title_bar.minimize_button is not None
    assert dialog.title_bar.close_button.accessibleName() == "关闭窗口"


def test_dialog_password_visibility_and_preference_relationship(qt_app):
    dialog = LoginDialog(api=_Api(), account_store=_Store())
    assert dialog.password_input.echoMode() == QLineEdit.Password
    assert dialog.visibility_action in dialog.password_input.actions()
    dialog.visibility_action.trigger()
    assert dialog.password_input.echoMode() == QLineEdit.Normal

    dialog.auto_checkbox.setChecked(True)
    assert dialog.remember_checkbox.isChecked() is True
    dialog.remember_checkbox.setChecked(False)
    assert dialog.auto_checkbox.isChecked() is False


def test_dialog_switches_between_login_and_register(qt_app):
    dialog = LoginDialog(api=_Api(), account_store=_Store())
    assert dialog.confirmation_input.isVisible() is False
    dialog._switch_mode()
    assert dialog._mode == "register"
    assert dialog.primary_button.text() == "注册并登录"
    dialog._switch_mode()
    assert dialog._mode == "login"


def test_authentication_worker_emits_success_and_finished():
    worker = AuthenticationWorker(
        {
            "mode": "login",
            "username": "User01",
            "password": "Pass01",
            "confirmation": "",
            "api": _Api(),
            "account_store": _Store(),
            "device_key": "device-key-001",
        }
    )
    completed = []
    failed = []
    finished = []
    worker.completed.connect(completed.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert len(completed) == 1
    assert failed == []
    assert finished == [True]


def test_authentication_worker_emits_unexpected_failure_and_finished():
    class FailingStore(_Store):
        def save_account(self, account):
            raise RuntimeError("store failed")

    worker = AuthenticationWorker(
        {
            "mode": "login",
            "username": "User01",
            "password": "Pass01",
            "confirmation": "",
            "api": _Api(),
            "account_store": FailingStore(),
            "device_key": "device-key-001",
        }
    )
    completed = []
    failed = []
    finished = []
    worker.completed.connect(completed.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert completed == []
    assert len(failed) == 1
    assert isinstance(failed[0], RuntimeError)
    assert finished == [True]


def test_dialog_busy_state_blocks_duplicate_submission_and_close(qt_app):
    dialog = LoginDialog(api=_Api(), account_store=_Store())
    dialog.username_input.setText("User01")
    dialog.password_input.setText("Pass01")

    dialog._set_busy(True)
    dialog._submit()
    dialog.reject()

    assert dialog._submitting is True
    assert dialog.primary_button.isEnabled() is False
    assert dialog.result() == 0


def test_dialog_failure_is_shown_only_after_thread_finishes(qt_app):
    dialog = LoginDialog(api=_Api(), account_store=_Store())
    error = PublicApiError("INVALID_CREDENTIALS", "internal detail", 401)
    dialog._set_busy(True)

    dialog._authentication_failed(error)
    assert dialog.status_label.text() != "账号或密码错误"

    dialog._thread_finished()

    assert dialog.status_label.text() == "账号或密码错误"
    assert dialog.status_label.property("error") is True
    assert dialog._submitting is False


def test_preferences_dialog_can_disable_auto_login(qt_app, monkeypatch):
    monkeypatch.setattr("apps.wps.login_window.windows_startup.set_enabled", lambda _enabled: None)
    store = type(
        "Store",
        (),
        {"update_preferences": lambda self, **kwargs: setattr(self, "updated", kwargs)},
    )()
    dialog = PreferencesDialog(
        account={"username": "User01", "password": "Pass01", "remember_password": True, "auto_login": True},
        account_store=store,
        startup_enabled=False,
    )
    assert dialog.windowIcon().isNull() is False
    assert dialog.windowFlags() & Qt.FramelessWindowHint
    assert dialog.title_bar.icon_label.pixmap().isNull() is False
    assert dialog.title_bar.minimize_button is None
    dialog.auto_checkbox.setChecked(False)

    dialog._save()

    assert store.updated == {"remember_password": True, "auto_login": False}
    assert dialog.result() == dialog.Accepted


def test_preferences_dialog_requires_login_before_restoring_password(qt_app):
    dialog = PreferencesDialog(
        account={"username": "User01", "password": "", "remember_password": False, "auto_login": False},
        account_store=_Store(),
        startup_enabled=False,
    )

    assert dialog.remember_checkbox.isEnabled() is False
    assert "重新登录" in dialog.status_label.text()


def test_desktop_tray_uses_the_shared_d_icon(qt_app, monkeypatch):
    pixmap = QPixmap(8, 8)
    pixmap.fill(Qt.red)
    expected_icon = QIcon(pixmap)
    monkeypatch.setattr(desktop_runtime, "login_window_icon", lambda: expected_icon)

    controller = desktop_runtime.DesktopController(
        application=qt_app,
        account_runtime=object(),
        start_service=lambda *_args, **_kwargs: None,
        port=9527,
    )

    assert controller._tray.icon().cacheKey() == expected_icon.cacheKey()
