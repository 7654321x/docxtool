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
    _configure_high_dpi,
    _login_icon_pixmap,
    password_mask,
    required_window_height,
    submit_account,
    window_geometry,
)
from apps.wps.public_api import PublicApiError
from apps.wps.user_messages import user_message_for_error


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
            "device": {
                "id": "wdev_1",
                "device_name": "测试电脑",
                "platform": "windows",
                "status": "active",
            },
            "session_token": "session-token-001",
            "session_created_at": 3600,
            "session_expires_at": 86400,
            "features": {"controlled": [{"command": "apply", "enabled": True}]},
            "config_version": "config-1",
            "heartbeat_interval_seconds": 600,
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


@pytest.mark.parametrize(
    ("code", "status", "expected"),
    [
        ("INVALID_CREDENTIALS", 401, "账号或密码不正确；若尚未注册，请先注册账号。"),
        ("USERNAME_TAKEN", 409, "该账号已注册，请直接登录。"),
        ("WPS_PUBLIC_SERVER_UNAVAILABLE", 0, "无法连接服务器，请检查网络后重试。"),
        ("WPS_PUBLIC_CLIENT_BLOCKED", 403, "客户端请求被访问规则拦截，请更新客户端或联系管理员。"),
        ("WPS_PUBLIC_RESPONSE_INVALID", 200, "服务器响应异常，请稍后重试。"),
        ("INTERNAL_ERROR", 500, "服务器处理异常，请稍后重试。"),
    ],
)
def test_user_messages_explain_public_api_failures(code, status, expected):
    assert user_message_for_error(PublicApiError(code, "internal detail", status)) == expected


def test_user_messages_explain_existing_login_window_conflict():
    assert user_message_for_error(RuntimeError("WPS_SINGLE_INSTANCE_LISTEN_FAILED")) == (
        "已有登录窗口或 DocxTool WPS 后台程序正在运行。"
        "请从任务栏或系统托盘打开它；若没有窗口，请退出旧程序后重试。"
    )


def test_user_messages_explain_when_an_old_instance_cannot_be_stopped():
    assert user_message_for_error(RuntimeError("WPS_SINGLE_INSTANCE_STOP_FAILED")) == (
        "检测到旧的 DocxTool WPS 进程，但无法自动结束。"
        "请从任务栏或系统托盘退出旧程序后重试。"
    )


def test_frozen_instance_cleanup_excludes_the_current_pyinstaller_pair(monkeypatch):
    output = (
        '"DocxToolWps.exe","99","Console","1","1 K"\n'
        '"DocxToolWps.exe","100","Console","1","1 K"\n'
        '"DocxToolWps.exe","301","Console","1","1 K"\n'
        '"DocxToolWps.exe","302","Console","1","1 K"\n'
    )
    monkeypatch.setattr(desktop_runtime, "_is_frozen_wps_executable", lambda: True)
    monkeypatch.setattr(desktop_runtime.sys, "executable", r"C:\Apps\DocxToolWps.exe")
    monkeypatch.setattr(desktop_runtime.os, "getpid", lambda: 100)
    monkeypatch.setattr(desktop_runtime.os, "getppid", lambda: 99)
    monkeypatch.setattr(
        desktop_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: type("Result", (), {"returncode": 0, "stdout": output})(),
    )

    assert desktop_runtime._other_frozen_wps_process_ids() == [301, 302]


def test_frozen_instance_cleanup_stops_only_verified_old_processes(monkeypatch):
    stopped = []
    events = []
    states = iter([True, False])
    monkeypatch.setattr(desktop_runtime, "_other_frozen_wps_process_ids", lambda: [301, 302])
    monkeypatch.setattr(desktop_runtime, "_running_single_instance", lambda: next(states))
    monkeypatch.setattr(desktop_runtime.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        desktop_runtime.subprocess,
        "run",
        lambda args, **_kwargs: stopped.append(args) or type("Result", (), {"returncode": 0})(),
    )
    monkeypatch.setattr(
        desktop_runtime,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append((event, fields or {})),
    )

    desktop_runtime._stop_previous_frozen_instance()

    assert stopped == [
        ["taskkill", "/PID", "301", "/T", "/F"],
        ["taskkill", "/PID", "302", "/T", "/F"],
    ]
    assert events[-1] == (
        "launcher.desktop.previous_instance.stop.completed",
        {"instance_count": 2},
    )


def test_single_instance_replaces_a_confirmed_old_frozen_instance(qt_app, monkeypatch):
    calls = []

    class Signal:
        @staticmethod
        def connect(_callback):
            return None

    class Server:
        def __init__(self, _parent):
            self.newConnection = Signal()

        @staticmethod
        def removeServer(name):
            calls.append(("remove", name))

        def listen(self, name):
            calls.append(("listen", name))
            return True

    monkeypatch.setattr(desktop_runtime, "QLocalServer", Server)
    monkeypatch.setattr(desktop_runtime, "_running_single_instance", lambda: True)
    monkeypatch.setattr(desktop_runtime, "_is_frozen_wps_executable", lambda: True)
    monkeypatch.setattr(
        desktop_runtime,
        "_stop_previous_frozen_instance",
        lambda: calls.append(("stop",)),
    )

    instance = desktop_runtime.SingleInstance()

    assert instance.acquire() is True
    assert calls == [
        ("stop",),
        ("remove", desktop_runtime.INSTANCE_NAME),
        ("listen", desktop_runtime.INSTANCE_NAME),
    ]


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
        auto_login=False,
    )

    assert dialog.username_input.text() == "User01"
    assert dialog.password_input.text() == "Pass01"
    assert dialog.remember_checkbox.isChecked() is True
    assert dialog.auto_checkbox.isChecked() is False
    assert dialog.startup_checkbox.isChecked() is False
    assert dialog.windowIcon().isNull() is False
    assert dialog.status_label.isVisible() is False
    assert dialog.password_input.width() == dialog.username_input.width()
    assert dialog.username_icon_action in dialog.username_input.actions()
    assert dialog.username_icon_action.icon().isNull() is False


def test_auto_login_submits_through_the_visible_login_dialog(qt_app, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        "apps.wps.login_window.QTimer.singleShot",
        lambda delay, callback: scheduled.append((delay, callback)),
    )
    dialog = LoginDialog(
        api=_Api(),
        account_store=_Store(),
        initial_username="User01",
        initial_password="Pass01",
        remember_password=True,
        auto_login=True,
    )
    submitted = []
    monkeypatch.setattr(dialog, "_submit", lambda: submitted.append(True))

    assert [delay for delay, _callback in scheduled] == [2000]
    scheduled[0][1]()

    assert submitted == [True]


def test_login_dialog_uses_native_title_bar_and_d_icon(qt_app):
    dialog = LoginDialog(api=_Api(), account_store=_Store())

    assert not dialog.windowFlags() & Qt.FramelessWindowHint
    assert dialog.windowFlags() & Qt.WindowTitleHint
    assert dialog.windowFlags() & Qt.WindowMinimizeButtonHint
    assert dialog.windowFlags() & Qt.WindowCloseButtonHint
    assert dialog.windowTitle() == "DocxTool WPS"
    assert dialog.windowIcon().isNull() is False
    assert _login_icon_pixmap(52).size().width() == 52
    assert _login_icon_pixmap(52).size().height() == 52


def test_dialog_password_visibility_and_preference_relationship(qt_app):
    dialog = LoginDialog(api=_Api(), account_store=_Store())
    assert dialog.password_input.echoMode() == QLineEdit.Password
    assert dialog.visibility_action in dialog.password_input.actions()
    dialog.visibility_action.trigger()
    assert dialog.password_input.echoMode() == QLineEdit.Normal
    assert dialog.confirmation_input.echoMode() == QLineEdit.Normal
    assert dialog.confirmation_visibility_action.isChecked() is True
    dialog.confirmation_visibility_action.trigger()
    assert dialog.password_input.echoMode() == QLineEdit.Password
    assert dialog.confirmation_input.echoMode() == QLineEdit.Password
    assert dialog.visibility_action.isChecked() is False

    dialog.auto_checkbox.setChecked(True)
    assert dialog.remember_checkbox.isChecked() is True
    dialog.remember_checkbox.setChecked(False)
    assert dialog.auto_checkbox.isChecked() is False


def test_dialog_switches_between_login_and_register(qt_app):
    dialog = LoginDialog(api=_Api(), account_store=_Store())
    assert dialog.confirmation_group.isHidden() is True
    assert dialog.height() <= 650
    dialog._switch_mode()
    assert dialog._mode == "register"
    assert dialog.primary_button.text() == "注册并登录"
    assert dialog.title_label.text() == "注册账号"
    assert dialog.confirmation_group.isHidden() is False
    register_height = dialog.height()
    dialog._switch_mode()
    assert dialog._mode == "login"
    assert dialog.confirmation_group.isHidden() is True
    assert dialog.height() <= register_height


def test_dialog_uses_shared_polished_component_contract(qt_app):
    dialog = LoginDialog(api=_Api(), account_store=_Store())

    assert dialog.card.objectName() == "AuthCard"
    assert dialog.title_label.objectName() == "PageTitle"
    assert dialog.hint_label.objectName() == "PageSubtitle"
    assert dialog.username_input.objectName() == "AuthInput"
    assert dialog.password_input.objectName() == "AuthInput"
    assert dialog.confirmation_input.objectName() == "AuthInput"
    assert dialog.remember_checkbox.objectName() == "PreferenceCheck"
    assert dialog.auto_checkbox.objectName() == "PreferenceCheck"
    assert dialog.startup_checkbox.objectName() == "PreferenceCheck"
    assert dialog.startup_checkbox.text() == "开机自启"
    assert dialog.status_label.objectName() == "ErrorLabel"
    assert dialog.primary_button.objectName() == "PrimaryButton"
    assert dialog.switch_button.objectName() == "FooterLink"
    assert 46 <= dialog.username_input.minimumHeight() <= 50
    assert 46 <= dialog.password_input.minimumHeight() <= 50
    assert 48 <= dialog.primary_button.minimumHeight() <= 50


def test_dialog_keeps_enter_submission_contract(qt_app, monkeypatch):
    dialog = LoginDialog(api=_Api(), account_store=_Store())
    submitted = []
    monkeypatch.setattr(dialog, "_submit", lambda: submitted.append(True))

    dialog.password_input.returnPressed.disconnect()
    dialog.password_input.returnPressed.connect(dialog._submit)
    dialog.password_input.returnPressed.emit()

    assert submitted == [True]


def test_high_dpi_attributes_remain_enabled_before_application_creation(monkeypatch):
    attributes = []

    class ApplicationProbe:
        @staticmethod
        def instance():
            return None

        @staticmethod
        def setAttribute(attribute, enabled):
            attributes.append((attribute, enabled))

    monkeypatch.setattr("apps.wps.login_window.configure_windows_application_identity", lambda: None)
    monkeypatch.setattr("apps.wps.login_window.QApplication", ApplicationProbe)

    _configure_high_dpi()

    assert attributes == [
        (Qt.AA_EnableHighDpiScaling, True),
        (Qt.AA_UseHighDpiPixmaps, True),
    ]


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
    assert dialog.status_label.text() != "账号或密码不正确；若尚未注册，请先注册账号。"

    dialog._thread_finished()

    assert dialog.status_label.text() == "账号或密码不正确；若尚未注册，请先注册账号。"
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
    assert dialog.startup_checkbox.text() == "开机自启"
    assert not dialog.windowFlags() & Qt.FramelessWindowHint
    assert dialog.windowFlags() & Qt.WindowTitleHint
    assert dialog.windowFlags() & Qt.WindowCloseButtonHint
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
    assert controller._startup_action.text() == "开机自启"


def test_desktop_reauthentication_uses_visible_login_without_old_password(qt_app, monkeypatch):
    calls = []

    class Runtime:
        def __init__(self):
            self.callback = None
            self.reloaded = 0

        def set_reauth_callback(self, callback):
            self.callback = callback

        def reload_account(self, account=None):
            assert account == {"username": "User01"}
            self.reloaded += 1

        @staticmethod
        def summary():
            return {"reauth_required": True}

    runtime = Runtime()
    monkeypatch.setattr(
        desktop_runtime.account_store,
        "load_account",
        lambda: {
            "username": "User01",
            "device_key": "device-key-001",
            "remember_password": True,
            "auto_login": True,
        },
    )
    monkeypatch.setattr(desktop_runtime.windows_startup, "is_enabled", lambda: False)
    monkeypatch.setattr(
        desktop_runtime,
        "show_login_register_window",
        lambda **kwargs: calls.append(kwargs) or {"username": "User01"},
    )
    controller = desktop_runtime.DesktopController(
        application=qt_app,
        account_runtime=runtime,
        start_service=lambda *_args, **_kwargs: None,
        port=9527,
        api=object(),
    )

    runtime.callback()

    assert len(calls) == 1
    assert calls[0]["initial_username"] == "User01"
    assert calls[0]["initial_password"] == ""
    assert calls[0]["auto_login"] is False
    assert "重新输入密码" in calls[0]["initial_message"]
    assert runtime.reloaded == 1
    assert controller._reauth_open is False


def test_desktop_reports_existing_wps_service_without_killing_it(qt_app, monkeypatch):
    messages = []
    events = []
    monkeypatch.setattr(
        desktop_runtime.QMessageBox,
        "critical",
        lambda _parent, title, message: messages.append((title, message)),
    )
    monkeypatch.setattr(
        desktop_runtime,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields or {})
        ),
    )

    class Application:
        def quit(self):
            events.append(("quit", {}))

    controller = desktop_runtime.DesktopController(
        application=Application(),
        account_runtime=object(),
        start_service=lambda *_args, **_kwargs: None,
        port=9527,
    )

    controller._handle_service_failure(RuntimeError("WPS_WEB_SERVER_PORT_IN_USE"))

    assert messages == [
        (
            "DocxTool WPS",
            "检测到已有 DocxTool WPS 本地服务正在运行。请从系统托盘退出旧服务后重新启动；"
            "为保护当前任务，程序未自动结束它。",
        )
    ]
    assert ("launcher.desktop.service.failed", {"error_code": "WPS_WEB_SERVER_PORT_IN_USE", "error_type": "RuntimeError"}) in events
