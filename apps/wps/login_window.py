"""PySide2 login and registration dialog shown before WPS services start."""

from __future__ import annotations

import ctypes
import sys

from PySide2.QtCore import QObject, QTimer, QRectF, Qt, QThread, Signal
from PySide2.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide2.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from docxtool.wps_server.validation import (
    WpsValidationError,
    validate_password,
    validate_username,
)

from .account_runtime import account_from_response, device_payload
from .control.logging_adapter import log_event
from .public_api import PublicApiError
from . import windows_startup


LOGIN_STYLE = """
QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei"; }
QDialog#LoginDialog { background: #EEF4F1; }
QFrame#BrandHeader { background: #E8F0ED; border: none; }
QLabel#Logo { background: transparent; border: none; }
QLabel#BrandName { color: #252B29; font-size: 28px; font-weight: 700; }
QScrollArea#AuthScroll { background: transparent; border: none; }
QScrollArea#AuthScroll > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { width: 8px; margin: 4px 1px; background: transparent; }
QScrollBar::handle:vertical { min-height: 28px; border-radius: 3px; background: #C7D2CE; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QFrame#AuthCard { background: #FFFFFF; border: 1px solid #E8ECEA; border-radius: 17px; }
QLabel#PageTitle { color: #252B29; font-size: 28px; font-weight: 700; }
QLabel#PageSubtitle { color: #808885; font-size: 14px; }
QLabel#FieldLabel { color: #3C4441; font-size: 14px; font-weight: 600; }
QLineEdit#AuthInput { min-height: 46px; max-height: 46px; border: 1px solid #D8E0DD; border-radius: 8px; padding: 0 14px; background: #FFFFFF; color: #252B29; font-size: 15px; selection-background-color: #789389; }
QLineEdit#AuthInput:hover { border-color: #BDC9C5; }
QLineEdit#AuthInput:focus { border-color: #789389; }
QLineEdit#AuthInput:disabled { background: #F4F6F5; color: #8C9692; }
QCheckBox#PreferenceCheck { color: #525A57; font-size: 14px; spacing: 8px; }
QCheckBox#PreferenceCheck::indicator { width: 18px; height: 18px; border: 1px solid #BFC9C5; border-radius: 4px; background: #FFFFFF; }
QCheckBox#PreferenceCheck::indicator:hover { border-color: #789389; }
QCheckBox#PreferenceCheck::indicator:checked { border-color: #226B5B; background: #226B5B; image: url(%CHECK_ICON%); }
QCheckBox#PreferenceCheck::indicator:disabled { border-color: #D7DDDA; background: #F0F2F1; }
QLabel#ErrorLabel { min-height: 20px; max-height: 36px; color: #7A8581; font-size: 13px; }
QLabel#ErrorLabel[error="true"] { color: #B65353; }
QPushButton#PrimaryButton { min-height: 48px; max-height: 48px; border: none; border-radius: 8px; background: #2D3331; color: #FFFFFF; font-size: 16px; font-weight: 600; }
QPushButton#PrimaryButton:hover { background: #39413E; }
QPushButton#PrimaryButton:pressed { background: #242927; }
QPushButton#PrimaryButton:disabled { background: #ADB5B2; color: #F4F5F4; }
QFrame#FooterSeparator { min-height: 1px; max-height: 1px; background: #EDF0EF; border: none; }
QPushButton#FooterLink { border: none; background: transparent; color: #26715F; font-size: 14px; font-weight: 600; padding: 4px; }
QPushButton#FooterLink:hover { color: #1D5E50; text-decoration: underline; }
QLabel#FooterPrompt { color: #8A918F; font-size: 14px; }
"""


APPLICATION_USER_MODEL_ID = "DocxTool.WPS.5.2"
_app_user_model_id_configured = False


def window_geometry(
    width: int,
    requested_height: int,
    screen_width: int,
    screen_height: int,
) -> str:
    height = max(1, int(requested_height))
    left = max(0, (int(screen_width) - int(width)) // 2)
    top = max(0, (int(screen_height) - height) // 2)
    return f"{int(width)}x{height}+{left}+{top}"


def required_window_height(
    content_top: int,
    requested_content_height: int,
    bottom_padding: int,
) -> int:
    return max(1, int(content_top) + int(requested_content_height) + int(bottom_padding))


def password_mask(visible: bool) -> str:
    return "" if visible else "*"


def _friendly_error(exc: BaseException) -> str:
    if isinstance(exc, PublicApiError):
        messages = {
            "INVALID_CREDENTIALS": "账号或密码错误",
            "SESSION_EXPIRED": "登录已过期，请重新登录",
            "ACCOUNT_DISABLED": "账号已停用",
            "DEVICE_DISABLED": "当前设备已停用",
            "WPS_PUBLIC_SERVER_UNAVAILABLE": "服务器暂时无法连接，请检查网络后重试。",
        }
        return messages.get(exc.code, "登录失败，请稍后重试。")
    if isinstance(exc, (WpsValidationError, ValueError)):
        return str(exc)
    return "登录失败，请稍后重试。"


def submit_account(
    *,
    mode: str,
    username: str,
    password: str,
    confirmation: str,
    api,
    account_store,
    device_key: str,
    remember_password: bool = False,
    auto_login: bool = False,
) -> dict:
    """Validate one form submission, authenticate it, and save the account."""
    if auto_login and not remember_password:
        raise ValueError("自动登录需要同时记住密码")
    validated_username, _ = validate_username(username)
    validated_password = validate_password(password)
    payload = {
        "username": validated_username,
        "password": validated_password,
        "device": device_payload(device_key),
    }
    if mode == "register":
        if confirmation != validated_password:
            raise ValueError("两次输入的密码不一致")
        response = api.register(payload)
    elif mode == "login":
        response = api.login(payload)
    else:
        raise ValueError("WPS_LOGIN_MODE_INVALID")
    account = account_from_response(
        response,
        origin=api.origin,
        username=validated_username,
        password=validated_password,
        device_key=device_key,
        remember_password=remember_password,
        auto_login=auto_login,
    )
    account_store.save_account(account)
    return account


class AuthenticationWorker(QObject):
    completed = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, kwargs: dict) -> None:
        super().__init__()
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            self.completed.emit(submit_account(**self._kwargs))
        except Exception as exc:
            self.failed.emit(exc)
        finally:
            self.finished.emit()


class BrandHeader(QFrame):
    """Static Qt5 brand header with optional low-cost decorative arcs."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("BrandHeader")
        self.setFixedHeight(128)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        for offset, alpha in ((0, 24), (18, 18), (36, 13)):
            painter.setPen(QPen(QColor(90, 130, 115, alpha), 1.0))
            arc = QRectF(self.width() * 0.57 + offset, 12 + offset / 3, 250, 150)
            painter.drawArc(arc, 18 * 16, 150 * 16)
        painter.end()


class LoginDialog(QDialog):
    def __init__(
        self,
        *,
        api,
        account_store,
        initial_username: str = "",
        initial_password: str = "",
        device_key: str = "",
        remember_password: bool = False,
        auto_login: bool = False,
        startup_enabled: bool = False,
        initial_message: str = "",
    ) -> None:
        super().__init__()
        self._api = api
        self._account_store = account_store
        self._device_key = device_key or account_store.new_device_key()
        self._result = {}
        self._mode = "login"
        self._submitting = False
        self._thread = None
        self._worker = None
        self._authentication_error = None
        self._startup_error = None
        self.setObjectName("LoginDialog")
        self.setWindowTitle("DocxTool WPS")
        self.setWindowIcon(login_window_icon())
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setMinimumWidth(500)
        self.setMaximumWidth(540)
        self.resize(520, 650)
        self.setStyleSheet(_login_style())
        self._build_ui()
        self.username_input.setText(initial_username)
        self.password_input.setText(initial_password)
        self.remember_checkbox.setChecked(remember_password)
        self.auto_checkbox.setChecked(auto_login)
        self.startup_checkbox.setChecked(startup_enabled)
        self._set_status(initial_message)
        self._update_mode()
        self.username_input.setFocus()
        if auto_login:
            QTimer.singleShot(2000, self._submit_auto_login)

    @property
    def account_result(self) -> dict:
        return dict(self._result)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = BrandHeader()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(52, 32, 42, 28)
        header_layout.setSpacing(0)
        logo = QLabel()
        logo.setObjectName("Logo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(52, 52)
        logo.setPixmap(_login_icon_pixmap(52))
        header_layout.addWidget(logo, 0, Qt.AlignVCenter)
        brand_name = QLabel("DocxTool")
        brand_name.setObjectName("BrandName")
        header_layout.addSpacing(19)
        header_layout.addWidget(brand_name, 0, Qt.AlignVCenter)
        header_layout.addStretch()
        root.addWidget(header)

        self.auth_scroll = QScrollArea()
        self.auth_scroll.setObjectName("AuthScroll")
        self.auth_scroll.setWidgetResizable(True)
        self.auth_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.auth_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(30, 0, 30, 20)
        self.card = QFrame()
        self.card.setObjectName("AuthCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(34, 30, 34, 26)
        card_layout.setSpacing(0)

        self.title_label = QLabel()
        self.title_label.setObjectName("PageTitle")
        self.hint_label = QLabel()
        self.hint_label.setObjectName("PageSubtitle")
        card_layout.addWidget(self.title_label)
        card_layout.addSpacing(7)
        card_layout.addWidget(self.hint_label)
        card_layout.addSpacing(25)

        self.username_group, self.username_input = self._field_group(
            "账号",
            "请输入账号",
        )
        self.username_icon_action = self.username_input.addAction(
            QIcon(str(_resource_path("images/user.svg"))),
            QLineEdit.TrailingPosition,
        )
        self.username_icon_action.setText("账号")
        card_layout.addWidget(self.username_group)
        card_layout.addSpacing(17)

        self.password_group, self.password_input = self._field_group(
            "密码",
            "请输入密码",
            password=True,
        )
        self.password_input.returnPressed.connect(self._submit)
        self.visibility_action = self.password_input.addAction(
            QIcon(str(_resource_path("images/eye.svg"))),
            QLineEdit.TrailingPosition,
        )
        self.visibility_action.setCheckable(True)
        self.visibility_action.setToolTip("显示密码")
        self.visibility_action.setText("显示密码")
        self.visibility_action.triggered.connect(self._toggle_password)
        card_layout.addWidget(self.password_group)

        self.confirmation_group, self.confirmation_input = self._field_group(
            "确认密码",
            "请再次输入密码",
            password=True,
        )
        self.confirmation_input.returnPressed.connect(self._submit)
        self.confirmation_visibility_action = self.confirmation_input.addAction(
            QIcon(str(_resource_path("images/eye.svg"))),
            QLineEdit.TrailingPosition,
        )
        self.confirmation_visibility_action.setCheckable(True)
        self.confirmation_visibility_action.setToolTip("显示密码")
        self.confirmation_visibility_action.setText("显示密码")
        self.confirmation_visibility_action.triggered.connect(self._toggle_password)
        self.confirmation_spacer = QWidget()
        self.confirmation_spacer.setFixedHeight(17)
        card_layout.addWidget(self.confirmation_spacer)
        card_layout.addWidget(self.confirmation_group)

        preference_row = QHBoxLayout()
        preference_row.setContentsMargins(0, 20, 0, 0)
        preference_row.setSpacing(0)
        self.remember_checkbox = QCheckBox("记住密码")
        self.auto_checkbox = QCheckBox("自动登录")
        self.remember_checkbox.setObjectName("PreferenceCheck")
        self.auto_checkbox.setObjectName("PreferenceCheck")
        self.remember_checkbox.toggled.connect(self._remember_changed)
        self.auto_checkbox.toggled.connect(self._auto_changed)
        preference_row.addWidget(self.remember_checkbox)
        preference_row.addSpacing(28)
        preference_row.addWidget(self.auto_checkbox)
        preference_row.addStretch()
        card_layout.addLayout(preference_row)

        self.startup_checkbox = QCheckBox("开机自启")
        self.startup_checkbox.setObjectName("PreferenceCheck")
        card_layout.addSpacing(11)
        card_layout.addWidget(self.startup_checkbox)

        self.status_label = QLabel()
        self.status_label.setObjectName("ErrorLabel")
        self.status_label.setWordWrap(True)
        card_layout.addSpacing(13)
        card_layout.addWidget(self.status_label)

        self.primary_button = QPushButton()
        self.primary_button.setObjectName("PrimaryButton")
        self.primary_button.setDefault(True)
        self.primary_button.clicked.connect(self._submit)
        card_layout.addSpacing(7)
        card_layout.addWidget(self.primary_button)

        footer_separator = QFrame()
        footer_separator.setObjectName("FooterSeparator")
        card_layout.addSpacing(23)
        card_layout.addWidget(footer_separator)

        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 15, 0, 0)
        switch_row.setSpacing(4)
        switch_row.addStretch()
        self.switch_prompt = QLabel()
        self.switch_prompt.setObjectName("FooterPrompt")
        self.switch_button = QPushButton()
        self.switch_button.setObjectName("FooterLink")
        self.switch_button.clicked.connect(self._switch_mode)
        switch_row.addWidget(self.switch_prompt)
        switch_row.addWidget(self.switch_button)
        switch_row.addStretch()
        card_layout.addLayout(switch_row)

        outer_layout.addWidget(self.card)
        outer_layout.addStretch()
        self.auth_scroll.setWidget(outer)
        root.addWidget(self.auth_scroll)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        self.setTabOrder(self.username_input, self.password_input)
        self.setTabOrder(self.password_input, self.remember_checkbox)
        self.setTabOrder(self.remember_checkbox, self.auto_checkbox)
        self.setTabOrder(self.auto_checkbox, self.primary_button)

    @staticmethod
    def _field_group(
        text: str,
        placeholder: str,
        *,
        password: bool = False,
    ) -> tuple:
        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        field = QLineEdit()
        field.setObjectName("AuthInput")
        field.setPlaceholderText(placeholder)
        field.setAccessibleName(text)
        if password:
            field.setEchoMode(QLineEdit.Password)
        layout.addWidget(label)
        layout.addWidget(field)
        return group, field

    def _update_mode(self) -> None:
        registering = self._mode == "register"
        self.title_label.setText("注册账号" if registering else "账号登录")
        self.hint_label.setText(
            "创建你的账号，开始使用 DocxTool WPS。"
            if registering
            else "欢迎回来，继续进入你的工作台。"
        )
        self.confirmation_spacer.setVisible(registering)
        self.confirmation_group.setVisible(registering)
        self.primary_button.setText("注册并登录" if registering else "登录")
        self.switch_prompt.setText("已有账号？" if registering else "还没有账号？")
        self.switch_button.setText("去登录" if registering else "注册账号")
        self._resize_for_mode()

    def _resize_for_mode(self) -> None:
        self.card.layout().activate()
        self.layout().activate()
        application = QApplication.instance()
        available_height = 800
        if application is not None and application.primaryScreen() is not None:
            available_height = application.primaryScreen().availableGeometry().height()
        preferred = 780 if self._mode == "register" else 690
        target_height = min(preferred, max(560, available_height - 40))
        center = self.frameGeometry().center()
        self.resize(520, target_height)
        if self.isVisible():
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def _switch_mode(self) -> None:
        if self._submitting:
            return
        self._mode = "register" if self._mode == "login" else "login"
        if self._mode == "register":
            log_event("INFO", "login", "login.register.opened", "已切换到 WPS 注册视图")
        self._set_status(
            "账号和密码至少 5 位，必须同时包含字母和数字"
            if self._mode == "register"
            else ""
        )
        self._update_mode()

    def _toggle_password(self, visible: bool) -> None:
        mode = QLineEdit.Normal if visible else QLineEdit.Password
        self.password_input.setEchoMode(mode)
        self.confirmation_input.setEchoMode(mode)
        icon = QIcon(
            str(_resource_path("images/eye-off.svg" if visible else "images/eye.svg"))
        )
        tooltip = "隐藏密码" if visible else "显示密码"
        for action in (self.visibility_action, self.confirmation_visibility_action):
            action.blockSignals(True)
            action.setChecked(visible)
            action.setIcon(icon)
            action.setToolTip(tooltip)
            action.setText(tooltip)
            action.blockSignals(False)
        log_event(
            "INFO",
            "login",
            "login.password.visibility.changed",
            "WPS 登录密码可见性已切换",
            {"visible": bool(visible)},
        )

    def _auto_changed(self, checked: bool) -> None:
        if checked and not self.remember_checkbox.isChecked():
            self.remember_checkbox.setChecked(True)

    def _submit_auto_login(self) -> None:
        if self._mode != "login" or not self.auto_checkbox.isChecked() or self._result:
            return
        log_event(
            "INFO",
            "login",
            "login.auto.window_submit",
            "登录窗口已显示，自动登录按登录按钮流程提交",
        )
        self._submit()

    def _remember_changed(self, checked: bool) -> None:
        if not checked and self.auto_checkbox.isChecked():
            self.auto_checkbox.setChecked(False)

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setProperty("error", error)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _set_busy(self, busy: bool) -> None:
        self._submitting = busy
        for widget in (
            self.username_input,
            self.password_input,
            self.confirmation_input,
            self.remember_checkbox,
            self.auto_checkbox,
            self.startup_checkbox,
            self.switch_button,
        ):
            widget.setEnabled(not busy)
        self.visibility_action.setEnabled(not busy)
        self.confirmation_visibility_action.setEnabled(not busy)
        self.primary_button.setEnabled(not busy)
        if busy:
            self.primary_button.setText("注册中…" if self._mode == "register" else "正在登录…")
        else:
            self.primary_button.setText("注册并登录" if self._mode == "register" else "登录")

    def _submit(self) -> None:
        if self._submitting:
            return
        mode = self._mode
        event = "login.register.submit.start" if mode == "register" else "login.submit.start"
        log_event("INFO", "login", event, "开始提交 WPS 账号认证")
        self._set_busy(True)
        self._set_status("正在连接账号服务...")
        kwargs = {
            "mode": mode,
            "username": self.username_input.text(),
            "password": self.password_input.text(),
            "confirmation": self.confirmation_input.text(),
            "api": self._api,
            "account_store": self._account_store,
            "device_key": self._device_key,
            "remember_password": self.remember_checkbox.isChecked(),
            "auto_login": self.auto_checkbox.isChecked(),
        }
        self._thread = QThread(self)
        self._worker = AuthenticationWorker(kwargs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.completed.connect(self._authentication_completed)
        self._worker.failed.connect(self._authentication_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    def _authentication_completed(self, account: dict) -> None:
        self._result = dict(account)
        try:
            windows_startup.set_enabled(self.startup_checkbox.isChecked())
        except OSError as exc:
            self._startup_error = exc
            log_event(
                "WARNING",
                "launcher",
                "launcher.startup.preference.failed",
                "Windows 启动偏好保存失败",
                {
                    "error_code": "WPS_STARTUP_PREFERENCE_FAILED",
                    "error_type": type(exc).__name__,
                },
            )
        event = (
            "login.register.submit.completed"
            if self._mode == "register"
            else "login.submit.completed"
        )
        log_event("INFO", "login", event, "WPS 账号认证与本地保存已完成")
        log_event(
            "INFO",
            "login",
            "login.preference.saved",
            "WPS 登录偏好已保存",
            {
                "remember_password": bool(account.get("remember_password")),
                "auto_login": bool(account.get("auto_login")),
            },
        )
        log_event(
            "INFO",
            "login",
            (
                "login.password.saved"
                if account.get("remember_password")
                else "login.password.cleared"
            ),
            (
                "WPS 登录密码已使用 DPAPI 保存"
                if account.get("remember_password")
                else "WPS 本地登录密码已清除"
            ),
        )

    def _authentication_failed(self, exc: BaseException) -> None:
        event = (
            "login.register.submit.failed"
            if self._mode == "register"
            else "login.submit.failed"
        )
        fields = {
            "error_code": exc.code if isinstance(exc, PublicApiError) else type(exc).__name__,
            "error_type": type(exc).__name__,
            "network_available": not exc.network if isinstance(exc, PublicApiError) else True,
        }
        log_event("WARNING", "login", event, "WPS 账号认证失败", fields)
        self._authentication_error = exc

    def _thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        if self._result:
            if self._startup_error is not None:
                QMessageBox.warning(
                    self,
                    "DocxTool WPS",
                    "账号登录成功，但无法修改 Windows 启动设置。",
                )
            self.accept()
            return
        error = self._authentication_error
        self._authentication_error = None
        if error is not None:
            self._set_status(_friendly_error(error), error=True)
        self._set_busy(False)

    def reject(self) -> None:
        if self._submitting:
            return
        super().reject()


class PreferencesDialog(QDialog):
    def __init__(
        self,
        *,
        account: dict,
        account_store,
        startup_enabled: bool,
    ) -> None:
        super().__init__()
        self._account_store = account_store
        self.setWindowTitle("DocxTool WPS 登录设置")
        self.setWindowIcon(login_window_icon())
        self.setObjectName("LoginDialog")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setMinimumWidth(450)
        self.setStyleSheet(_login_style())
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 28)
        root.setSpacing(0)
        card = QFrame()
        card.setObjectName("AuthCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(30, 28, 30, 28)
        root.addWidget(card)
        title = QLabel("登录与启动设置")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        layout.addSpacing(7)
        hint = QLabel(f"当前账号：{account['username']}")
        hint.setObjectName("PageSubtitle")
        layout.addWidget(hint)
        layout.addSpacing(20)
        self.remember_checkbox = QCheckBox("记住密码")
        self.remember_checkbox.setObjectName("PreferenceCheck")
        self.remember_checkbox.setChecked(bool(account.get("remember_password")))
        if not account.get("password"):
            self.remember_checkbox.setEnabled(False)
        self.auto_checkbox = QCheckBox("自动登录")
        self.auto_checkbox.setObjectName("PreferenceCheck")
        self.auto_checkbox.setChecked(bool(account.get("auto_login")))
        self.startup_checkbox = QCheckBox("开机自启")
        self.startup_checkbox.setObjectName("PreferenceCheck")
        self.startup_checkbox.setChecked(startup_enabled)
        self.remember_checkbox.toggled.connect(self._remember_changed)
        self.auto_checkbox.toggled.connect(self._auto_changed)
        layout.addWidget(self.remember_checkbox)
        layout.addSpacing(9)
        layout.addWidget(self.auto_checkbox)
        layout.addSpacing(9)
        layout.addWidget(self.startup_checkbox)
        layout.addSpacing(20)
        self.status_label = QLabel(
            "自动登录只会在登录窗口显示后自动提交。"
            if account.get("password")
            else "如需重新记住密码，请先退出当前账号并重新登录。"
        )
        self.status_label.setObjectName("ErrorLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addSpacing(12)
        save_button = QPushButton("保存设置")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save)
        layout.addWidget(save_button)

    def _auto_changed(self, checked: bool) -> None:
        if checked and not self.remember_checkbox.isChecked():
            self.remember_checkbox.setChecked(True)

    def _remember_changed(self, checked: bool) -> None:
        if not checked and self.auto_checkbox.isChecked():
            self.auto_checkbox.setChecked(False)

    def _save(self) -> None:
        try:
            self._account_store.update_preferences(
                remember_password=self.remember_checkbox.isChecked(),
                auto_login=self.auto_checkbox.isChecked(),
            )
            windows_startup.set_enabled(self.startup_checkbox.isChecked())
        except (OSError, ValueError, RuntimeError) as exc:
            self.status_label.setText(_friendly_error(exc))
            self.status_label.setProperty("error", True)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            return
        log_event(
            "INFO",
            "login",
            "login.preference.saved",
            "WPS 登录与启动偏好已保存",
            {
                "remember_password": self.remember_checkbox.isChecked(),
                "auto_login": self.auto_checkbox.isChecked(),
                "startup_enabled": self.startup_checkbox.isChecked(),
            },
        )
        self.accept()


def _resource_path(relative: str):
    from pathlib import Path

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative


def _login_style() -> str:
    return LOGIN_STYLE.replace(
        "%CHECK_ICON%",
        str(_resource_path("images/check.svg")).replace("\\", "/"),
    )


def login_window_icon() -> QIcon:
    return QIcon(str(_resource_path("images/login-window.png")))


def _login_icon_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(str(_resource_path("images/login-window.png")))
    if pixmap.isNull():
        raise RuntimeError("WPS_LOGIN_WINDOW_ICON_INVALID")
    # The shared icon includes a light safe area for native window chrome.
    # Crop it only for the large in-page brand mark; system icons keep the
    # complete asset through ``login_window_icon()``.
    cropped = pixmap.copy(10, 12, 48, 48)
    return cropped.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def configure_windows_application_identity() -> None:
    global _app_user_model_id_configured
    if sys.platform != "win32" or _app_user_model_id_configured:
        return
    result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        APPLICATION_USER_MODEL_ID
    )
    if result != 0:
        raise OSError(result, "WPS_APP_USER_MODEL_ID_FAILED")
    _app_user_model_id_configured = True


def _configure_high_dpi() -> None:
    configure_windows_application_identity()
    if QApplication.instance() is not None:
        return
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def show_login_register_window(
    *,
    api,
    account_store,
    initial_username: str = "",
    initial_password: str = "",
    device_key: str = "",
    remember_password: bool = False,
    auto_login: bool = False,
    startup_enabled: bool = False,
    initial_message: str = "",
) -> dict:
    _configure_high_dpi()
    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setWindowIcon(login_window_icon())
    application.setFont(application.font())
    log_event("INFO", "login", "login.window.opened", "WPS 登录注册窗口已打开")
    dialog = LoginDialog(
        api=api,
        account_store=account_store,
        initial_username=initial_username,
        initial_password=initial_password,
        device_key=device_key,
        remember_password=remember_password,
        auto_login=auto_login,
        startup_enabled=startup_enabled,
        initial_message=initial_message,
    )
    screen = application.primaryScreen().availableGeometry()
    target_height = min(690, max(560, screen.height() - 40))
    dialog.resize(520, target_height)
    dialog.move(
        screen.left() + max(0, (screen.width() - dialog.width()) // 2),
        screen.top() + max(0, (screen.height() - dialog.height()) // 2),
    )
    dialog.exec_()
    return dialog.account_result


def show_preferences_window(*, account: dict, account_store) -> bool:
    dialog = PreferencesDialog(
        account=account,
        account_store=account_store,
        startup_enabled=windows_startup.is_enabled(),
    )
    return dialog.exec_() == QDialog.Accepted
