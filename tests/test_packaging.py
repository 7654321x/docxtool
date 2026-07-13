from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_import_docxtool_has_no_database_side_effect(tmp_path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    result = subprocess.run(
        [sys.executable, "-c", "import docxtool; print(docxtool.__name__)"],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert result.stdout.strip() == "docxtool"
    assert not list(tmp_path.rglob("stats.db*"))
