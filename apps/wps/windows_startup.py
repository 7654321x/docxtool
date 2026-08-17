"""Current-user Windows startup registration for the WPS launcher."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import winreg


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DocxToolWps"
STARTUP_ARGUMENT = "--startup"


def _source_windowless_python() -> Path:
    """Return the source-runtime executable that never allocates a console."""
    executable = Path(sys.executable).resolve()
    windowless = executable.with_name("pythonw.exe")
    if not windowless.is_file():
        raise OSError("WPS_STARTUP_PYTHONW_MISSING")
    return windowless


def _registered_startup_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return None


def _is_legacy_source_command(value: object) -> bool:
    """Recognize only the older source launcher stored under our own Run value."""
    if not isinstance(value, str):
        return False
    normalized = value.replace("/", "\\").casefold()
    return "\\apps\\wps\\main.py" in normalized and STARTUP_ARGUMENT in normalized


def launcher_command() -> str:
    if bool(getattr(sys, "frozen", False)):
        parts = [str(Path(sys.executable).resolve()), STARTUP_ARGUMENT]
    else:
        parts = [
            str(_source_windowless_python()),
            str(Path(__file__).with_name("main.py")),
            STARTUP_ARGUMENT,
        ]
    return subprocess.list2cmdline(parts)


def is_enabled() -> bool:
    registered = _registered_startup_value()
    if registered is None:
        return False
    value, value_type = registered
    if value_type != winreg.REG_SZ or not isinstance(value, str):
        return False
    try:
        return value == launcher_command() or _is_legacy_source_command(value)
    except OSError:
        return _is_legacy_source_command(value)


def migrate_legacy_registration() -> bool:
    """Replace the recognized Python-console startup value with the current launcher."""
    registered = _registered_startup_value()
    if registered is None:
        return False
    value, value_type = registered
    if value_type != winreg.REG_SZ or not _is_legacy_source_command(value):
        return False
    if value == launcher_command():
        return False
    set_enabled(True)
    return True


def set_enabled(enabled: bool) -> None:
    if enabled:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launcher_command())
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return


def restart_command(*arguments: str) -> list:
    if bool(getattr(sys, "frozen", False)):
        return [sys.executable, *arguments]
    return [sys.executable, str(Path(__file__).with_name("main.py")), *arguments]


def launch(*arguments: str) -> None:
    subprocess.Popen(
        restart_command(*arguments),
        cwd=os.getcwd(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
