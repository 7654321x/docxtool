from __future__ import annotations

import base64
import json
from importlib import resources

import pytest

from docxtool.document.style_config import PageSettings, StyleRule, load_rules_and_settings
from docxtool.paths import default_format_config_path
from docxtool.web import app as server


def _format_config_headers(config: dict) -> dict[str, str]:
    raw = json.dumps(config, ensure_ascii=False).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return {
        "X-Format-Config": encoded,
        "X-Format-Config-Encoding": "base64url-json",
    }


def test_default_format_config_is_packaged_resource() -> None:
    config = resources.files("docxtool.resources").joinpath("config/default-format.json")

    assert config.is_file()
    data = json.loads(config.read_text(encoding="utf-8"))
    assert len(data["styles"]) == 24
    assert data["page"]["lines_per_page"] == 22
    assert "size" not in data["styles"][6]
    assert "size" not in data["styles"][7]


def test_default_format_config_loads_without_current_working_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    config_path = default_format_config_path()
    rules = StyleRule.from_config()
    settings = PageSettings.from_config()

    assert config_path.name == "default-format.json"
    assert rules[0].level_name
    assert settings.lines_per_page == 22


def test_default_format_config_is_valid_x_format_config() -> None:
    config = resources.files("docxtool.resources").joinpath("config/default-format.json")
    data = json.loads(config.read_text(encoding="utf-8"))

    rules, settings, features = load_rules_and_settings(data)
    decoded = server._decode_format_config(_format_config_headers(data))

    assert len(data["styles"]) == 24
    assert len(rules) == 24
    assert rules[6].font_size_label == StyleRule.default_for_row(6).font_size_label
    assert rules[7].font_size_label == StyleRule.default_for_row(7).font_size_label
    assert settings.lines_per_page == 22
    assert features["numbered_bold_enabled"] is True
    assert rules[17].spacing_before == 1.0
    assert rules[18].spacing_before == 0.0
    assert decoded == data


def test_explicit_empty_style_size_is_rejected_as_x_format_config() -> None:
    config = {"styles": [{"size": ""}], "page": {}}

    with pytest.raises(ValueError, match=r"FORMAT_CONFIG_INVALID: styles\[0\]\.size"):
        server._decode_format_config(_format_config_headers(config))
