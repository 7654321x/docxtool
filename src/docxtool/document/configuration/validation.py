"""格式配置校验、功能开关和配置加载。"""

from __future__ import annotations

from docxtool.document.errors import ConfigValidationError
from .models import (
    PageSettings,
    StyleRule,
    _bool_field,
    _nonempty_string_field,
    _safe_bool,
    finite_float,
)

def validate_format_config(config_dict: dict) -> dict:
    if not isinstance(config_dict, dict):
        raise ConfigValidationError("config", "必须是 JSON 对象")
    StyleRule.from_config_dict(config_dict)
    PageSettings.from_config_dict(config_dict)
    _parse_core_feature_options(config_dict)
    normalized = dict(config_dict)
    if config_dict.get("letterhead") is not None:
        from docxtool.document.letterhead_config import normalize_letterhead_config

        normalized["letterhead"] = normalize_letterhead_config(config_dict["letterhead"])
    return normalized


def _safe_mode(field_path: str, value, allowed: set[str], default: str) -> str:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        raise ConfigValidationError(field_path, f"必须是 {', '.join(sorted(allowed))} 之一")
    return normalized


def _dict_field(config_dict: dict, key: str) -> dict:
    value = config_dict.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        legacy_enabled = _legacy_feature_enabled(key, value)
        if legacy_enabled is not None:
            return {"enabled": legacy_enabled}
        raise ConfigValidationError(key, "必须是对象或布尔值")
    return value


def _legacy_feature_enabled(field_path: str, value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on", "启用", "是"}:
            return True
        if raw in {"0", "false", "no", "off", "禁用", "否"}:
            return False
    return None


def _scope_options(field_path: str, value) -> dict:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ConfigValidationError(field_path, "必须是对象")
    return {
        "body": _safe_bool(value.get("body", True), True),
        "tables": _safe_bool(value.get("tables", False), False),
        "headers": _safe_bool(value.get("headers", False), False),
        "footers": _safe_bool(value.get("footers", False), False),
    }


def _parse_core_feature_options(config_dict: dict) -> dict:
    punctuation = _dict_field(config_dict, "punctuation")
    classification = _dict_field(config_dict, "classification")
    numbering = _dict_field(config_dict, "numbering")
    page_number = _dict_field(config_dict, "page_number")
    signature_block = _dict_field(config_dict, "signature_block")
    table_format = _dict_field(config_dict, "table_format")
    cleanup = _dict_field(config_dict, "cleanup")
    processing = _dict_field(config_dict, "processing")
    raw_features = config_dict.get("features", {})
    legacy_page_number_enabled = None
    if isinstance(raw_features, dict) and "page_number_enabled" in raw_features:
        legacy_page_number_enabled = _safe_bool(raw_features.get("page_number_enabled"), True)
    if "enabled" in page_number:
        page_number_enabled = _bool_field(page_number, "enabled", "page_number.enabled", True)
    elif legacy_page_number_enabled is not None:
        page_number_enabled = legacy_page_number_enabled
    else:
        page_number_enabled = True
    raw_processing_mode = (
        processing.get("strategy")
        or processing.get("mode")
        or config_dict.get("processing_mode")
        or config_dict.get("mode")
        or "smart"
    )
    if not isinstance(raw_processing_mode, str):
        raise ConfigValidationError("processing.mode", "必须是字符串")
    processing_mode = raw_processing_mode.strip().lower()
    processing_strategy = {
        "smart": "structural",
        "structural": "structural",
        "strict": "strict",
        "normalize": "normalize",
    }.get(processing_mode)
    if processing_strategy is None:
        raise ConfigValidationError(
            "processing.mode",
            "仅支持 smart、strict、normalize 或 structural",
        )
    return {
        "processing": {
            "strategy": processing_strategy,
        },
        "punctuation": {
            "enabled": _safe_bool(punctuation.get("enabled", False), False),
            "mode": _safe_mode("punctuation.mode", punctuation.get("mode", "safe"), {"off", "safe", "standard"}, "safe"),
            "scope": _scope_options("punctuation.scope", punctuation.get("scope", {})),
        },
        "classification": {
            "enabled": _safe_bool(classification.get("enabled", True), True),
            "minimum_auto_format_confidence": finite_float(
                "classification.minimum_auto_format_confidence",
                classification.get("minimum_auto_format_confidence", 0.85),
                0,
                1,
            ),
        },
        "numbering": {
            "enabled": _safe_bool(numbering.get("enabled", False), False),
            "mode": _safe_mode("numbering.mode", numbering.get("mode", "safe"), {"off", "safe"}, "safe"),
        },
        "page_number": {
            "enabled": page_number_enabled,
            "font_name": _nonempty_string_field(
                page_number, "font_name", "page_number.font_name", "宋体"
            ),
            "font_size_pt": finite_float(
                "page_number.font_size_pt",
                page_number.get("font_size_pt", 14),
                1,
                72,
            ),
            "bold": _bool_field(page_number, "bold", "page_number.bold", False),
            "style": _safe_mode(
                "page_number.style",
                page_number.get("style", "dash"),
                {"plain", "number", "page", "dash", "cn", "chinese", "cn_total", "chinese_total", "page_numpages"},
                "dash",
            ),
            "position": _safe_mode(
                "page_number.position",
                page_number.get("position", "outside"),
                {"left", "center", "centre", "right", "outside"},
                "outside",
            ),
            "first_page": _bool_field(
                page_number, "first_page", "page_number.first_page", True
            ),
            "section_numbering": _safe_mode(
                "page_number.section_numbering",
                page_number.get("section_numbering", "continue"),
                {"continue", "restart", "restart_each_section", "new"},
                "continue",
            ),
            "offset_from_text_mm": finite_float(
                "page_number.offset_from_text_mm",
                page_number.get("offset_from_text_mm", 7),
                0,
                30,
            ),
        },
        "signature_block": {
            "mode": _safe_mode(
                "signature_block.mode",
                signature_block.get("mode", "preserve"),
                {"preserve", "without_seal", "with_seal"},
                "preserve",
            ),
        },
        "table_format": {
            "enabled": _safe_bool(table_format.get("enabled", False), False),
            "smart_alignment": _safe_bool(table_format.get("smart_alignment", False), False),
        },
        "cleanup": {
            "enabled": _safe_bool(cleanup.get("enabled", False), False),
            "mode": _safe_mode("cleanup.mode", cleanup.get("mode", "safe"), {"off", "safe"}, "safe"),
        },
    }

def load_rules_and_settings(config_dict: dict = None):
    """加载本次任务的 rules/settings/features。

    config_dict 为空时使用服务器默认格式配置；不为空时只对当前任务生效。
    """
    if config_dict:
        rules = StyleRule.from_config_dict(config_dict)
        settings = PageSettings.from_config_dict(config_dict)
        raw_features = config_dict.get("features", {}) if isinstance(config_dict, dict) else {}
        if not isinstance(raw_features, dict):
            raw_features = {}
    else:
        rules = StyleRule.from_config()
        settings = PageSettings.from_config()
        raw_features = {}
    features = {
        "numbered_bold_enabled": _safe_bool(raw_features.get("numbered_bold_enabled", True), True),
        "punctuation_enabled": _safe_bool(raw_features.get("punctuation_enabled", True), True),
        "page_number_enabled": _safe_bool(raw_features.get("page_number_enabled", True), True),
    }
    if isinstance(config_dict, dict):
        features.update(_parse_core_feature_options(config_dict))
        from docxtool.document.letterhead_config import normalize_letterhead_config

        features["letterhead"] = normalize_letterhead_config(config_dict.get("letterhead"))
    else:
        features.update(_parse_core_feature_options({}))
        from docxtool.document.letterhead_config import default_letterhead_config

        features["letterhead"] = default_letterhead_config()
    return rules, settings, features
