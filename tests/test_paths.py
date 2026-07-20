from __future__ import annotations

import sysconfig
from pathlib import Path

from docxtool import paths


def test_default_runtime_paths_use_project_var_in_source_tree() -> None:
    assert paths.var_path("data", "stats.db") == Path.cwd() / "var" / "data" / "stats.db"
    assert paths.runtime_dir("logs", "LOG_DIR") == Path.cwd() / "var" / "logs"


def test_runtime_dir_honors_environment_override(monkeypatch, tmp_path: Path) -> None:
    override = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(override))

    assert paths.runtime_dir("logs", "LOG_DIR") == override


def test_relative_runtime_override_is_resolved_from_project_root(monkeypatch) -> None:
    monkeypatch.setenv("LOG_DIR", "custom/logs")

    assert paths.runtime_dir("logs", "LOG_DIR") == paths.PROJECT_ROOT / "custom" / "logs"


def test_user_data_root_stays_out_of_site_packages(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCXTOOL_HOME", str(tmp_path / "docxtool-home"))

    root = paths._user_data_root()
    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()

    assert root == tmp_path / "docxtool-home"
    assert site_packages not in root.resolve().parents
