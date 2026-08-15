"""Qt desktop lifetime, tray menu, and single-instance routing."""

from __future__ import annotations

import ctypes
import threading

from PySide2.QtCore import QObject, Signal
from PySide2.QtNetwork import QLocalServer, QLocalSocket
from PySide2.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import account_store, windows_startup
from .control.logging_adapter import log_event
from .login_window import (
    _configure_high_dpi,
    login_window_icon,
    show_login_register_window,
    show_preferences_window,
)


INSTANCE_NAME = "DocxToolWps-5.2"


def shift_pressed() -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)


def ensure_application() -> QApplication:
    _configure_high_dpi()
    application = QApplication.instance() or QApplication([])
    application.setWindowIcon(login_window_icon())
    application.setQuitOnLastWindowClosed(False)
    return application


class SingleInstance(QObject):
    show_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._read_messages)

    def acquire(self) -> bool:
        probe = QLocalSocket()
        probe.connectToServer(INSTANCE_NAME)
        if probe.waitForConnected(300):
            probe.write(b"show-settings")
            probe.waitForBytesWritten(300)
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(INSTANCE_NAME)
        if not self._server.listen(INSTANCE_NAME):
            raise RuntimeError("WPS_SINGLE_INSTANCE_LISTEN_FAILED")
        return True

    def _read_messages(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.waitForReadyRead(300)
            if bytes(socket.readAll()) == b"show-settings":
                self.show_requested.emit()
            socket.disconnectFromServer()

    def close(self) -> None:
        self._server.close()
        QLocalServer.removeServer(INSTANCE_NAME)


class DesktopController(QObject):
    service_failed = Signal(object)
    reauth_requested = Signal()

    def __init__(self, *, application, account_runtime, start_service, port: int, api=None) -> None:
        super().__init__()
        self._application = application
        self._account_runtime = account_runtime
        self._start_service = start_service
        self._port = port
        self._api = api
        self._stop = threading.Event()
        self._service_error = None
        self.restart_login_requested = False
        self._settings_open = False
        self._reauth_open = False
        self._service_thread = threading.Thread(target=self._run_service, daemon=True)
        self.service_failed.connect(self._handle_service_failure)
        self.reauth_requested.connect(self._open_reauthentication)
        set_reauth_callback = getattr(self._account_runtime, "set_reauth_callback", None)
        if callable(set_reauth_callback):
            set_reauth_callback(self._request_reauthentication)
        self._tray = QSystemTrayIcon(login_window_icon(), self)
        self._tray.setToolTip("DocxTool WPS")
        menu = QMenu()
        settings_action = menu.addAction("登录与账号设置")
        settings_action.triggered.connect(self.show_settings)
        logout_action = menu.addAction("退出当前账号")
        logout_action.triggered.connect(self.logout)
        menu.addSeparator()
        self._startup_action = menu.addAction("开机自启")
        self._startup_action.setCheckable(True)
        self._startup_action.setChecked(windows_startup.is_enabled())
        self._startup_action.toggled.connect(self._set_startup)
        menu.addSeparator()
        quit_action = menu.addAction("退出 DocxTool WPS")
        quit_action.triggered.connect(application.quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_activated)

    def start(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError("WPS_SYSTEM_TRAY_UNAVAILABLE")
        self._service_thread.start()
        self._tray.show()

    def _run_service(self) -> None:
        try:
            self._start_service(
                self._port,
                self._account_runtime,
                stop_event=self._stop,
            )
        except BaseException as exc:
            self._service_error = exc
            self.service_failed.emit(exc)

    def _handle_service_failure(self, exc: BaseException) -> None:
        error_code = str(exc)
        if error_code not in {
            "WPS_WEB_SERVER_PORT_IN_USE",
            "WPS_WEB_SERVER_OLD_SERVICE_STOP_FAILED",
        }:
            error_code = "WPS_DESKTOP_SERVICE_FAILED"
        message = (
            "检测到已有 DocxTool WPS 本地服务正在运行。请从系统托盘退出旧服务后重新启动；"
            "为保护当前任务，程序未自动结束它。"
            if error_code == "WPS_WEB_SERVER_PORT_IN_USE"
            else "旧 DocxTool WPS 本地服务自动停止失败，请从系统托盘退出旧服务后重新启动。"
            if error_code == "WPS_WEB_SERVER_OLD_SERVICE_STOP_FAILED"
            else "后台服务启动失败，请查看日志。"
        )
        log_event(
            "ERROR",
            "launcher",
            "launcher.desktop.service.failed",
            "DocxTool WPS 后台服务异常退出",
            {"error_code": error_code, "error_type": type(exc).__name__},
        )
        QMessageBox.critical(None, "DocxTool WPS", message)
        self._application.quit()

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_settings()

    def _request_reauthentication(self) -> None:
        """Receive a worker-thread request and queue the actual dialog on the Qt thread."""
        self.reauth_requested.emit()

    def _open_reauthentication(self) -> None:
        """Run the existing login flow without reusing or pre-filling the old password."""
        if self._reauth_open or self._api is None:
            return
        account = account_store.load_account()
        if not account:
            return
        self._reauth_open = True
        try:
            result = show_login_register_window(
                api=self._api,
                account_store=account_store,
                initial_username=account.get("username", ""),
                initial_password="",
                device_key=account.get("device_key", ""),
                remember_password=bool(account.get("remember_password", False)),
                auto_login=False,
                startup_enabled=windows_startup.is_enabled(),
                initial_message="登录会话已失效，请重新输入密码完成认证。",
            )
            if result:
                self._account_runtime.reload_account(result)
                log_event(
                    "INFO",
                    "account",
                    "account.reauth.completed",
                    "WPS 账号重新认证完成",
                )
        except Exception as exc:
            log_event(
                "ERROR",
                "account",
                "account.reauth.error",
                "WPS 账号重新认证窗口处理失败",
                {
                    "error_code": "WPS_REAUTH_WINDOW_FAILED",
                    "error_type": type(exc).__name__,
                },
            )
            QMessageBox.warning(None, "DocxTool WPS", "重新认证失败，请从托盘再次打开登录与账号设置。")
        finally:
            self._reauth_open = False

    def show_settings(self) -> None:
        if self._settings_open:
            return
        summary = getattr(self._account_runtime, "summary", lambda: {})()
        if summary.get("reauth_required"):
            self._open_reauthentication()
            return
        account = account_store.load_account()
        if not account:
            return
        self._settings_open = True
        try:
            if show_preferences_window(account=account, account_store=account_store):
                self._account_runtime.reload_account()
                self._startup_action.blockSignals(True)
                self._startup_action.setChecked(windows_startup.is_enabled())
                self._startup_action.blockSignals(False)
        finally:
            self._settings_open = False

    def logout(self) -> None:
        try:
            self._account_runtime.logout()
        except Exception as exc:
            log_event(
                "WARNING",
                "login",
                "login.logout.failed",
                "WPS 账号退出失败",
                {"error_code": type(exc).__name__, "error_type": type(exc).__name__},
            )
            QMessageBox.warning(None, "DocxTool WPS", "退出登录失败，请检查网络后重试。")
            return
        log_event("INFO", "login", "login.logout.completed", "WPS 账号已退出")
        self.restart_login_requested = True
        self._stop.set()
        self._application.quit()

    def _set_startup(self, checked: bool) -> None:
        try:
            windows_startup.set_enabled(checked)
        except OSError as exc:
            self._startup_action.blockSignals(True)
            self._startup_action.setChecked(not checked)
            self._startup_action.blockSignals(False)
            QMessageBox.warning(None, "DocxTool WPS", "无法修改 Windows 启动设置。")
            log_event(
                "WARNING",
                "launcher",
                "launcher.startup.preference.failed",
                "Windows 启动偏好保存失败",
                {"error_code": "WPS_STARTUP_PREFERENCE_FAILED", "error_type": type(exc).__name__},
            )

    def shutdown(self) -> None:
        self._tray.hide()
        self._stop.set()
        self._service_thread.join(timeout=8)
        if self._service_thread.is_alive():
            raise RuntimeError("WPS_DESKTOP_SERVICE_STOP_TIMEOUT")
        if self._service_error is not None:
            raise self._service_error
