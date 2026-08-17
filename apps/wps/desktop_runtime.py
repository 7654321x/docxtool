"""Qt desktop lifetime, tray menu, and single-instance routing."""

from __future__ import annotations

import csv
import ctypes
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

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
from .user_messages import error_code_for, user_message_for_error


INSTANCE_NAME = "DocxToolWps-5.2"
_FROZEN_EXECUTABLE_NAME = "docxtoolwps.exe"
_OLD_INSTANCE_STOP_TIMEOUT_SECONDS = 3


def shift_pressed() -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)


def ensure_application() -> QApplication:
    _configure_high_dpi()
    application = QApplication.instance() or QApplication([])
    application.setWindowIcon(login_window_icon())
    application.setQuitOnLastWindowClosed(False)
    return application


def _is_frozen_wps_executable() -> bool:
    """Limit automatic process termination to the packaged WPS client."""
    return (
        bool(getattr(sys, "frozen", False))
        and sys.platform == "win32"
        and Path(sys.executable).name.casefold() == _FROZEN_EXECUTABLE_NAME
    )


def _other_frozen_wps_process_ids() -> list[int]:
    """Return older DocxTool WPS process IDs, excluding this PyInstaller chain."""
    if not _is_frozen_wps_executable():
        return []
    try:
        result = subprocess.run(
            [
                "tasklist",
                "/FI",
                f"IMAGENAME eq {Path(sys.executable).name}",
                "/FO",
                "CSV",
                "/NH",
            ],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []

    protected = {os.getpid(), os.getppid()}
    process_ids: list[int] = []
    for row in csv.reader(StringIO(result.stdout)):
        if len(row) < 2 or row[0].casefold() != Path(sys.executable).name.casefold():
            continue
        try:
            process_id = int(row[1])
        except ValueError:
            continue
        if process_id not in protected:
            process_ids.append(process_id)
    return sorted(set(process_ids))


def _running_single_instance() -> bool:
    """Return whether another process currently owns our local instance channel."""
    probe = QLocalSocket()
    probe.connectToServer(INSTANCE_NAME)
    connected = probe.waitForConnected(250)
    if connected:
        probe.disconnectFromServer()
    return connected


def _stop_previous_frozen_instance() -> None:
    """Force-stop a confirmed older packaged instance before a new one takes over."""
    process_ids = _other_frozen_wps_process_ids()
    if not process_ids:
        raise RuntimeError("WPS_SINGLE_INSTANCE_STOP_FAILED")
    log_event(
        "WARNING",
        "launcher",
        "launcher.desktop.previous_instance.detected",
        "检测到旧的 DocxTool WPS 实例，准备自动结束后重新启动",
        {"error_code": "WPS_SINGLE_INSTANCE_PREVIOUS", "instance_count": len(process_ids)},
    )
    stop_errors: list[str] = []
    for process_id in process_ids:
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process_id), "/T", "/F"],
                capture_output=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                text=True,
            )
        except OSError as exc:
            stop_errors.append(type(exc).__name__)
            continue
        if result.returncode != 0:
            stop_errors.append("TASKKILL_FAILED")

    deadline = time.monotonic() + _OLD_INSTANCE_STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not _running_single_instance():
            log_event(
                "INFO",
                "launcher",
                "launcher.desktop.previous_instance.stop.completed",
                "旧的 DocxTool WPS 实例已结束，继续启动新实例",
                {"instance_count": len(process_ids)},
            )
            return
        time.sleep(0.05)

    error = RuntimeError("WPS_SINGLE_INSTANCE_STOP_FAILED")
    log_event(
        "ERROR",
        "launcher",
        "launcher.desktop.previous_instance.stop.failed",
        "旧的 DocxTool WPS 实例自动结束失败",
        {
            "error_code": "WPS_SINGLE_INSTANCE_STOP_FAILED",
            "error_type": type(error).__name__,
            "instance_count": len(process_ids),
            "taskkill_error_count": len(stop_errors),
        },
    )
    raise error


class SingleInstance(QObject):
    show_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._read_messages)

    def acquire(self) -> bool:
        if _running_single_instance():
            if _is_frozen_wps_executable():
                _stop_previous_frozen_instance()
            else:
                probe = QLocalSocket()
                probe.connectToServer(INSTANCE_NAME)
                if probe.waitForConnected(300):
                    probe.write(b"show-settings")
                    probe.waitForBytesWritten(300)
                    probe.disconnectFromServer()
                return False
        QLocalServer.removeServer(INSTANCE_NAME)
        if not self._server.listen(INSTANCE_NAME):
            # A simultaneous launch may have acquired the channel after its
            # stale-instance cleanup. Leave that live instance alone.
            if _running_single_instance():
                return False
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


def show_startup_error(exc: BaseException) -> None:
    """Log and present a safe explanation for a desktop startup failure."""
    error_code = error_code_for(exc) or "WPS_DESKTOP_START_FAILED"
    log_event(
        "ERROR",
        "launcher",
        "launcher.desktop.startup.failed",
        "DocxTool WPS 启动失败",
        {"error_code": error_code, "error_type": type(exc).__name__},
    )
    QMessageBox.critical(None, "DocxTool WPS", user_message_for_error(exc))


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
        self._service_failure_reported = False
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
        error_code = error_code_for(exc)
        if error_code not in {
            "WPS_WEB_SERVER_PORT_IN_USE",
            "WPS_WEB_SERVER_OLD_SERVICE_STOP_FAILED",
        }:
            error_code = "WPS_DESKTOP_SERVICE_FAILED"
        message = user_message_for_error(RuntimeError(error_code))
        log_event(
            "ERROR",
            "launcher",
            "launcher.desktop.service.failed",
            "DocxTool WPS 后台服务异常退出",
            {"error_code": error_code, "error_type": type(exc).__name__},
        )
        self._service_failure_reported = True
        QMessageBox.critical(None, "DocxTool WPS", message)
        self._application.quit()

    @property
    def service_failure_reported(self) -> bool:
        return self._service_failure_reported

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
            QMessageBox.warning(None, "DocxTool WPS", user_message_for_error(exc))
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
            QMessageBox.warning(None, "DocxTool WPS", user_message_for_error(exc))
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
            QMessageBox.warning(
                None,
                "DocxTool WPS",
                user_message_for_error(RuntimeError("WPS_STARTUP_PREFERENCE_FAILED")),
            )
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
