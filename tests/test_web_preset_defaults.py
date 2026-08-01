from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from docxtool.web.preset_defaults import (
    core_feature_config_defaults,
    default_preset_config,
    seed_default_presets,
)


def _connect(db_path: Path) -> sqlite3.Connection:
    """传入数据库路径，返回带 Row 工厂的测试连接。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _rule(**overrides):
    """传入覆盖字段，返回模拟 StyleRule 的轻量对象。"""
    data = {
        "row_index": 1,
        "level_name": "正文",
        "font": "仿宋_GB2312",
        "font_size_label": "三号",
        "bold": False,
        "numbering_pattern": "",
        "language": "zh",
        "first_line_indent": 2,
        "alignment": "left",
        "spacing_before": 0,
        "spacing_after": 0,
        "left_indent": 0,
        "right_indent": 0,
        "page_break_before": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _page_settings():
    """无需传入数据，返回模拟 PageSettings 的轻量对象。"""
    return SimpleNamespace(
        page_width_cm=21,
        page_height_cm=29.7,
        margin_top_cm=3.7,
        margin_bottom_cm=3.5,
        margin_left_cm=2.8,
        margin_right_cm=2.6,
        lines_per_page=22,
        chars_per_line=28,
        line_spacing_value=28,
        space_before_line=0,
        space_after_line=0,
        grid_alignment=True,
    )


def test_default_preset_config_uses_style_rules_page_settings_and_core_features() -> None:
    config = default_preset_config(
        [_rule(level_name="标题", font_size_label="二号", bold=True)],
        _page_settings(),
        lambda _row: _rule(font_size_label="三号"),
    )

    assert config["schema_version"] == 1
    assert config["styles"][0]["name"] == "标题"
    assert config["styles"][0]["size"] == "二号"
    assert config["styles"][0]["bold"] is True
    assert config["page"]["chars_per_line"] == 28
    assert config["page_number"]["enabled"] is True
    assert config["punctuation"]["mode"] == "safe"
    assert config["features"]["numbered_bold_enabled"] is True


def test_default_preset_config_falls_back_to_default_size() -> None:
    config = default_preset_config(
        [_rule(font_size_label="")],
        _page_settings(),
        lambda _row: _rule(font_size_label="三号"),
    )

    assert config["styles"][0]["size"] == "三号"


def test_core_feature_config_defaults_are_independent_dicts() -> None:
    first = core_feature_config_defaults()
    second = core_feature_config_defaults()
    first["punctuation"]["enabled"] = True

    assert second["punctuation"]["enabled"] is False


def test_seed_default_presets_inserts_once(tmp_path: Path) -> None:
    conn = _connect(tmp_path / "presets.db")
    try:
        conn.execute(
            """CREATE TABLE presets(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                config_json TEXT NOT NULL,
                is_system INTEGER DEFAULT 0,
                is_default INTEGER DEFAULT 0,
                version INTEGER DEFAULT 1,
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            )"""
        )
        seed_default_presets(conn, lambda: {"schema_version": 1}, lambda: "2026-08-02 01:00:00")
        seed_default_presets(conn, lambda: {"schema_version": 2}, lambda: "2026-08-02 02:00:00")
        rows = conn.execute("SELECT * FROM presets WHERE id='official_document'").fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "党政机关公文格式"
    assert row["is_system"] == 1
    assert row["is_default"] == 1
    assert json.loads(row["config_json"]) == {"schema_version": 1}
    assert row["created_at"] == "2026-08-02 01:00:00"
