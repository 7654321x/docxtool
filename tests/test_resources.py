from __future__ import annotations

import json
from importlib import resources

from docxtool.document.style_config import PageSettings, StyleRule
from docxtool.paths import default_format_config_path


def test_default_format_config_is_packaged_resource() -> None:
    config = resources.files("docxtool.resources").joinpath("config/default-format.json")

    assert config.is_file()
    data = json.loads(config.read_text(encoding="utf-8"))
    assert len(data["styles"]) >= 24
    assert data["page"]["lines_per_page"] == 22


def test_default_format_config_loads_without_current_working_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    config_path = default_format_config_path()
    rules = StyleRule.from_config()
    settings = PageSettings.from_config()

    assert config_path.name == "default-format.json"
    assert rules[0].level_name
    assert settings.lines_per_page == 22
