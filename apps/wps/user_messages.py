"""Translate stable WPS failures into safe, action-oriented user messages."""

from __future__ import annotations

import re

from docxtool.wps_server.validation import WpsValidationError

from .public_api import PublicApiError


_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")

_MESSAGES = {
    "INVALID_CREDENTIALS": "账号或密码不正确；若尚未注册，请先注册账号。",
    "USERNAME_TAKEN": "该账号已注册，请直接登录。",
    "SESSION_REQUIRED": "请先登录账号。",
    "SESSION_INVALID": "登录状态无效，请重新登录。",
    "SESSION_EXPIRED": "登录已过期，请重新登录。",
    "ACCOUNT_DISABLED": "账号已停用，请联系管理员。",
    "DEVICE_DISABLED": "当前设备已停用，请联系管理员。",
    "DEVICE_MISMATCH": "当前设备与登录信息不一致，请重新登录。",
    "RATE_LIMITED": "请求过于频繁，请稍后再试。",
    "INTERNAL_ERROR": "服务器处理异常，请稍后重试。",
    "WPS_PUBLIC_SERVER_UNAVAILABLE": "无法连接服务器，请检查网络后重试。",
    "WPS_PUBLIC_CLIENT_BLOCKED": "客户端请求被访问规则拦截，请更新客户端或联系管理员。",
    "WPS_PUBLIC_RESPONSE_INVALID": "服务器响应异常，请稍后重试。",
    "WPS_PUBLIC_REQUEST_ID_MISMATCH": "服务器响应校验失败，请重试。",
    "WPS_SERVER_ORIGIN_INVALID": "客户端服务器地址配置无效，请更新或重新安装客户端。",
    "WPS_CLIENT_CONFIG_INVALID": "客户端服务配置无效，请更新或重新安装客户端。",
    "WPS_SINGLE_INSTANCE_LISTEN_FAILED": (
        "已有登录窗口或 DocxTool WPS 后台程序正在运行。"
        "请从任务栏或系统托盘打开它；若没有窗口，请退出旧程序后重试。"
    ),
    "WPS_SINGLE_INSTANCE_STOP_FAILED": (
        "检测到旧的 DocxTool WPS 进程，但无法自动结束。"
        "请从任务栏或系统托盘退出旧程序后重试。"
    ),
    "WPS_SYSTEM_TRAY_UNAVAILABLE": "系统托盘不可用，无法启动 DocxTool WPS 后台程序。",
    "WPS_WEB_SERVER_PORT_IN_USE": (
        "检测到已有 DocxTool WPS 本地服务正在运行。请从系统托盘退出旧服务后重新启动；"
        "为保护当前任务，程序未自动结束它。"
    ),
    "WPS_WEB_SERVER_OLD_SERVICE_STOP_FAILED": "旧的 DocxTool WPS 本地服务停止失败，请从系统托盘退出后重试。",
    "WPS_DESKTOP_SERVICE_FAILED": "DocxTool WPS 后台服务启动失败，请退出旧程序后重试。",
    "WPS_DESKTOP_START_FAILED": "DocxTool WPS 启动失败，请退出后重新打开客户端。",
    "WPS_DESKTOP_SERVICE_STOP_TIMEOUT": "DocxTool WPS 后台服务停止超时，请退出客户端后重试。",
    "WPS_LOCAL_ACCOUNT_CORRUPTED": "本机登录信息异常，请重新登录。",
    "WPS_LOCAL_ACCOUNT_QUARANTINE_FAILED": "本机登录信息无法恢复，请退出客户端后重试。",
    "WPS_LOCAL_ACCOUNT_INVALID": "本机登录信息异常，请重新登录。",
    "WPS_LOCAL_ACCOUNT_MISSING": "未找到本机登录信息，请重新登录。",
    "WPS_STARTUP_PREFERENCE_FAILED": "无法保存开机自启设置，请检查 Windows 权限后重试。",
    "WPS_STARTUP_PYTHONW_MISSING": "本机启动组件不完整，无法启用开机自启。",
    "WPS_APPDATA_MISSING": "无法访问 Windows 用户数据目录，请检查当前用户配置后重试。",
    "WPS_PACKAGE_JSON_INVALID": "客户端安装文件不完整或损坏，请重新安装 DocxTool WPS。",
    "WPS_APP_FILES_MISSING": "客户端安装文件不完整或损坏，请重新安装 DocxTool WPS。",
    "WPSJS_VERSION_NOT_PINNED": "客户端组件版本异常，请更新或重新安装客户端。",
    "WPSJS_RPC_VERSION_NOT_PINNED": "客户端组件版本异常，请更新或重新安装客户端。",
    "WPS_LOGIN_WINDOW_ICON_INVALID": "客户端界面资源异常，请更新或重新安装客户端。",
    "WPS_PUBLISH_XML_INVALID": "无法更新 WPS 加载项注册，请关闭 WPS 后重试。",
    "WPS_PUBLISH_XML_SCHEMA_INVALID": "WPS 加载项注册信息异常，请关闭 WPS 后重试。",
    "WPS_UNPUBLISH_XML_INVALID": "无法更新 WPS 加载项注册，请关闭 WPS 后重试。",
    "WPS_UNPUBLISH_XML_SCHEMA_INVALID": "WPS 加载项注册信息异常，请关闭 WPS 后重试。",
    "WPS_UNPUBLISH_WRITE_FAILED": "无法写入 WPS 加载项注册，请检查权限后重试。",
}


def error_code_for(exc: BaseException) -> str:
    """Return a stable error code when an exception exposes one."""
    code = getattr(exc, "code", "")
    if isinstance(code, str) and _ERROR_CODE_RE.fullmatch(code):
        return code
    text = str(exc).strip()
    prefix = text.split(":", 1)[0]
    return prefix if _ERROR_CODE_RE.fullmatch(prefix) else ""


def _compact_message(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:160]


def user_message_for_error(exc: BaseException) -> str:
    """Return a user-facing message without exposing implementation details."""
    code = error_code_for(exc)
    if code in _MESSAGES:
        return _MESSAGES[code]
    if isinstance(exc, WpsValidationError):
        return _compact_message(exc.message) or "输入内容不符合要求，请检查后重试。"
    if isinstance(exc, PublicApiError):
        if exc.status >= 500:
            return _MESSAGES["INTERNAL_ERROR"]
        message = _compact_message(exc.message)
        return message or "服务器返回了无法识别的错误，请稍后重试。"
    if isinstance(exc, ValueError):
        message = _compact_message(str(exc))
        if message and not _ERROR_CODE_RE.fullmatch(message):
            return message
    return "客户端出现异常，请退出 DocxTool WPS 后重试。"
