"""Default public preset configuration and seed data for the Web app."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable


def default_preset_config(style_rules: Iterable, page_settings, default_rule_for_row: Callable) -> dict:
    """传入样式规则、页面设置和默认规则查找函数，返回默认公文模板配置字典。"""
    styles = []
    for rule in style_rules:
        default_rule = default_rule_for_row(rule.row_index)
        styles.append(
            {
                "name": rule.level_name,
                "font": rule.font,
                "size": rule.font_size_label or default_rule.font_size_label,
                "bold": rule.bold,
                "pattern": rule.numbering_pattern,
                "lang": rule.language,
                "indent": rule.first_line_indent,
                "align": rule.alignment,
                "spacing_before": rule.spacing_before,
                "spacing_after": rule.spacing_after,
                "left_indent": rule.left_indent,
                "right_indent": rule.right_indent,
                "page_break_before": rule.page_break_before,
            }
        )
    config = {
        "schema_version": 1,
        "styles": styles,
        "page": _page_settings_to_dict(page_settings),
        "features": {
            "numbered_bold_enabled": True,
            "punctuation_enabled": True,
        },
    }
    config.update(core_feature_config_defaults())
    return config


def core_feature_config_defaults() -> dict:
    """无需传入数据，返回 Web 默认模板中的功能开关配置。"""
    return {
        "punctuation": {
            "enabled": False,
            "mode": "safe",
            "scope": {"body": True, "tables": False, "headers": False, "footers": False},
        },
        "classification": {
            "enabled": True,
            "minimum_auto_format_confidence": 0.85,
        },
        "numbering": {
            "enabled": False,
            "mode": "safe",
        },
        "page_number": {
            "enabled": True,
            "style": "dash",
            "position": "outside",
            "font_name": "宋体",
            "font_size_pt": 14,
            "bold": False,
            "first_page": True,
            "section_numbering": "continue",
            "offset_from_text_mm": 7,
        },
        "signature_block": {
            "mode": "without_seal",
        },
        "table_format": {
            "enabled": False,
            "smart_alignment": False,
        },
        "cleanup": {
            "enabled": False,
            "mode": "safe",
        },
    }


def seed_default_presets(conn, config_factory: Callable[[], dict], now_func: Callable[[], str]) -> None:
    """传入连接、配置工厂和时间函数，缺省时插入官方默认模板并返回 None。"""
    try:
        row = conn.execute("SELECT 1 FROM presets WHERE id=?", ("official_document",)).fetchone()
        if row:
            return
        config_json = json.dumps(config_factory(), ensure_ascii=False)
        now = now_func()
        conn.execute(
            """INSERT INTO presets
               (id, name, description, config_json, is_system, is_default, version, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                "official_document",
                "党政机关公文格式",
                "默认公文格式，适合通知、报告、请示、汇报等正式材料。",
                config_json,
                1,
                1,
                1,
                now,
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()


def _page_settings_to_dict(settings) -> dict:
    """传入 PageSettings 对象，返回可写入预设 JSON 的页面配置字典。"""
    return {
        "width_cm": settings.page_width_cm,
        "height_cm": settings.page_height_cm,
        "margin_top_cm": settings.margin_top_cm,
        "margin_bottom_cm": settings.margin_bottom_cm,
        "margin_left_cm": settings.margin_left_cm,
        "margin_right_cm": settings.margin_right_cm,
        "lines_per_page": settings.lines_per_page,
        "chars_per_line": settings.chars_per_line,
        "line_spacing_pt": settings.line_spacing_value,
        "space_before_line": settings.space_before_line,
        "space_after_line": settings.space_after_line,
        "grid_alignment": settings.grid_alignment,
    }
