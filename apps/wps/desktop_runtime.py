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

    def __init__(self, *, application, account_runtime, start_service, port: int) -> None:
        super().__init__()
        self._application = application
        self._account_runtime = account_runtime
        self._start_service = start_service
        self._port = port
        self._stop = threading.Event()
        self._service_error = None
        self.restart_login_requested = False
        self._settings_open = False
        self._service_thread = threading.Thread(target=self._run_service, daemon=True)
        self.service_failed.connect(self._handle_service_failure)
        self._tray = QSystemTrayIcon(login_window_icon(), self)
        self._tray.setToolTip("DocxTool WPS")
        menu = QMenu()
        settings_action = menu.addAction("登录与账号设置")
        settings_action.triggered.connect(self.show_settings)
        logout_action = menu.addAction("退出当前账号")
        logout_action.triggered.connect(self.logout)
        menu.addSeparator()
        self._startup_action = menu.addAction("随 Windows 登录启动")
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
        log_event(
            "ERROR",
            "launcher",
            "launcher.desktop.service.failed",
            "DocxTool WPS 后台服务异常退出",
            {"error_code": "WPS_DESKTOP_SERVICE_FAILED", "error_type": type(exc).__name__},
        )
        QMessageBox.critical(None, "DocxTool WPS", "后台服务启动失败，请查看日志。")
        self._application.quit()

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_settings()

    def show_settings(self) -> None:
        if self._settings_open:
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
