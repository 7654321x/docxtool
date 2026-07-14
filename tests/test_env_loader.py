from __future__ import annotations

import os
from pathlib import Path

from docxtool.env import load_dotenv_file


def test_load_dotenv_file_sets_missing_values_without_overriding(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# local settings",
                "ADMIN_TOKEN='from-file'",
                'PROXY_SECRET="proxy-from-file"',
                "BIND_HOST=127.0.0.1",
                "MALFORMED",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOKEN", "from-process")
    monkeypatch.delenv("PROXY_SECRET", raising=False)
    monkeypatch.delenv("BIND_HOST", raising=False)

    loaded = load_dotenv_file(env_file)

    assert loaded == {"PROXY_SECRET", "BIND_HOST"}
    assert os.environ["ADMIN_TOKEN"] == "from-process"
    assert os.environ["PROXY_SECRET"] == "proxy-from-file"
    assert os.environ["BIND_HOST"] == "127.0.0.1"
