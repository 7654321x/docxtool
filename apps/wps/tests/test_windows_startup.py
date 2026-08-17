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


def test_source_startup_command_uses_pythonw_to_avoid_a_console(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    command = windows_startup.launcher_command()

    assert "pythonw.exe" in command.casefold()
    assert "main.py" in command
    assert "--startup" in command


def test_legacy_source_startup_value_is_migrated_to_current_launcher(monkeypatch):
    legacy = r"C:\DocxTool\.venv\Scripts\python.exe C:\DocxTool\apps\wps\main.py --startup"
    calls = []

    monkeypatch.setattr(windows_startup.winreg, "OpenKey", lambda *_args: _Key())
    monkeypatch.setattr(
        windows_startup.winreg,
        "QueryValueEx",
        lambda *_args: (legacy, windows_startup.winreg.REG_SZ),
    )
    monkeypatch.setattr(windows_startup, "launcher_command", lambda: r"C:\DocxToolWps.exe --startup")
    monkeypatch.setattr(windows_startup, "set_enabled", lambda enabled: calls.append(enabled))

    assert windows_startup.migrate_legacy_registration() is True
    assert calls == [True]


def test_restart_launch_uses_create_no_window(monkeypatch):
    calls = []
    monkeypatch.setattr(windows_startup, "restart_command", lambda *args: ["launcher.exe", *args])
    monkeypatch.setattr(windows_startup.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(
        windows_startup.subprocess,
        "Popen",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    windows_startup.launch("--force-login")

    assert calls[0][0] == (["launcher.exe", "--force-login"],)
    assert calls[0][1]["creationflags"] == 0x08000000
