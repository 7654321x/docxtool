from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_module_help_does_not_create_database_or_runtime_dirs(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["DOCXTOOL_HOME"] = str(tmp_path / "home")
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    result = subprocess.run(
        [sys.executable, "-m", "docxtool", "--help"],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert "Usage: python -m docxtool" in result.stdout
    assert not list(tmp_path.rglob("stats.db*"))
    assert not (tmp_path / "home").exists()
