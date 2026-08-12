"""Current-user Windows startup registration for the WPS launcher."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import winreg


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DocxToolWps"


def launcher_command() -> str:
    if bool(getattr(sys, "frozen", False)):
        parts = [str(Path(sys.executable).resolve()), "--startup"]
    else:
        parts = [str(Path(sys.executable).resolve()), str(Path(__file__).with_name("main.py")), "--startup"]
    return subprocess.list2cmdline(parts)


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, value_type = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return value_type == winreg.REG_SZ and value == launcher_command()


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
