import subprocess
import sys

from apps.wps import windows_startup


class _Key:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_startup_registration_uses_current_user_run_key(monkeypatch):
    calls = []
    monkeypatch.setattr(windows_startup.winreg, "CreateKeyEx", lambda *args: calls.append(("open", args)) or _Key())
    monkeypatch.setattr(windows_startup.winreg, "SetValueEx", lambda *args: calls.append(("set", args)))

    windows_startup.set_enabled(True)

    assert calls[0][1][0] == windows_startup.winreg.HKEY_CURRENT_USER
    assert calls[0][1][1] == windows_startup.RUN_KEY
    assert calls[1][1][1] == windows_startup.VALUE_NAME
    assert calls[1][1][4] == windows_startup.launcher_command()


def test_startup_registration_can_be_disabled_when_value_is_missing(monkeypatch):
    monkeypatch.setattr(
        windows_startup.winreg,
        "OpenKey",
        lambda *_args: (_ for _ in ()).throw(FileNotFoundError()),
    )

    windows_startup.set_enabled(False)
    assert windows_startup.is_enabled() is False


def test_source_startup_command_uses_current_python_and_hidden_flag(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    command = windows_startup.launcher_command()

    assert subprocess.list2cmdline([str(windows_startup.Path(sys.executable).resolve())]) in command
    assert "main.py" in command
    assert "--startup" in command
