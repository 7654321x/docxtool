"""Preset template validation and serialization helpers."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from docxtool.document.style_config import load_rules_and_settings


def normalize_template_name(name: str) -> str:
    """传入外部模板名称，返回压缩空白后的合法名称；非法时抛出 ValueError。"""
    cleaned = re.sub(r"\s+", " ", str(name or "")).strip()
    if not cleaned:
        raise ValueError("TEMPLATE_NAME_REQUIRED: 模板名称不能为空")
    if len(cleaned) > 80:
        raise ValueError("TEMPLATE_NAME_TOO_LONG: 模板名称不能超过 80 个字符")
    return cleaned


def normalize_template_id(value: str) -> str:
    """传入外部模板 ID，返回仅含安全字符的模板 ID；非法时抛出 ValueError。"""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        raise ValueError("TEMPLATE_ID_INVALID: 模板 ID 无效")
    if len(cleaned) > 80:
        raise ValueError("TEMPLATE_ID_TOO_LONG: 模板 ID 不能超过 80 个字符")
    return cleaned


def validate_template_config(config_obj: Mapping[str, Any], *, core_feature_defaults: Mapping[str, Any]) -> dict:
    """传入模板配置和核心功能默认值，返回可持久化的归一化模板配置。"""
    if not isinstance(config_obj, Mapping):
        raise ValueError("TEMPLATE_CONFIG_INVALID: config_json 必须是 JSON 对象")
    rules, settings, features = load_rules_and_settings(dict(config_obj))
    styles = []
    for rule in rules:
        styles.append({
            "name": rule.level_name,
            "font": rule.font,
            "size": rule.font_size_label,
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
        })
    normalized = {
        "schema_version": int(config_obj.get("schema_version", 1) or 1),
        "styles": styles,
        "page": {
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
        },
        "features": {
            "numbered_bold_enabled": bool(features.get("numbered_bold_enabled", True)),
            "punctuation_enabled": bool(features.get("punctuation_enabled", True)),
        },
    }
    for key in (
        "punctuation",
        "classification",
        "numbering",
        "page_number",
        "signature_block",
        "table_format",
        "cleanup",
    ):
        normalized[key] = features.get(key, core_feature_defaults[key])
    for key in ("mode", "processing_mode", "preset_id", "preset_name", "template_type", "source", "output_suffix", "global"):
        if key in config_obj:
            normalized[key] = config_obj[key]
    return normalized


def preset_row_to_dict(row: Mapping[str, Any], include_config: bool = False) -> dict:
    """传入数据库 preset 行和配置开关，返回面向 API 的脱敏模板字典。"""
    data = dict(row)
    data["is_system"] = bool(data.get("is_system"))
    data["is_default"] = bool(data.get("is_default"))
    data["visibility"] = data.get("visibility") or "public"
    data.pop("owner_id", None)
    if include_config:
        try:
            data["config_json"] = json.loads(data.get("config_json") or "{}")
        except json.JSONDecodeError:
            data["config_json"] = {}
    else:
        data.pop("config_json", None)
    return data
