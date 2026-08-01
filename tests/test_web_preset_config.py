from __future__ import annotations

import pytest

from docxtool.web.preset_config import (
    normalize_template_id,
    normalize_template_name,
    preset_row_to_dict,
    validate_template_config,
)


def _core_defaults() -> dict:
    return {
        "punctuation": {"enabled": False},
        "classification": {"enabled": True},
        "numbering": {"enabled": False},
        "page_number": {"enabled": True},
        "signature_block": {"mode": "without_seal"},
        "table_format": {"enabled": False},
        "cleanup": {"enabled": False},
    }


def test_normalize_template_name_trims_internal_whitespace() -> None:
    assert normalize_template_name("  我的   模板\t名称  ") == "我的 模板 名称"
    with pytest.raises(ValueError, match="TEMPLATE_NAME_REQUIRED"):
        normalize_template_name("   ")
    with pytest.raises(ValueError, match="TEMPLATE_NAME_TOO_LONG"):
        normalize_template_name("x" * 81)


def test_normalize_template_id_keeps_only_safe_characters() -> None:
    assert normalize_template_id("  abc/中文?..id  ") == "abc_..id"
    with pytest.raises(ValueError, match="TEMPLATE_ID_INVALID"):
        normalize_template_id("...")
    with pytest.raises(ValueError, match="TEMPLATE_ID_TOO_LONG"):
        normalize_template_id("x" * 81)


def test_validate_template_config_normalizes_page_styles_and_features() -> None:
    normalized = validate_template_config(
        {
            "schema_version": 1,
            "processing_mode": "smart",
            "page": {"lines_per_page": 22, "chars_per_line": 28},
            "punctuation": {"enabled": True, "mode": "safe"},
            "numbering": {"enabled": True},
        },
        core_feature_defaults=_core_defaults(),
    )

    assert normalized["schema_version"] == 1
    assert normalized["processing_mode"] == "smart"
    assert normalized["page"]["lines_per_page"] == 22
    assert normalized["page"]["chars_per_line"] == 28
    assert normalized["punctuation"]["enabled"] is True
    assert normalized["numbering"]["enabled"] is True
    assert normalized["classification"]["enabled"] is True
    assert normalized["classification"]["minimum_auto_format_confidence"] == 0.85
    assert normalized["styles"]


def test_validate_template_config_rejects_non_mapping() -> None:
    with pytest.raises(ValueError, match="TEMPLATE_CONFIG_INVALID"):
        validate_template_config([], core_feature_defaults=_core_defaults())  # type: ignore[arg-type]


def test_preset_row_to_dict_redacts_owner_and_optionally_parses_config() -> None:
    row = {
        "id": "tpl_demo",
        "name": "Demo",
        "is_system": 1,
        "is_default": 0,
        "visibility": "",
        "owner_id": "usr_secret",
        "config_json": '{"schema_version":1}',
    }

    without_config = preset_row_to_dict(row, include_config=False)
    with_config = preset_row_to_dict(row, include_config=True)

    assert without_config["is_system"] is True
    assert without_config["is_default"] is False
    assert without_config["visibility"] == "public"
    assert "owner_id" not in without_config
    assert "config_json" not in without_config
    assert with_config["config_json"] == {"schema_version": 1}


def test_preset_row_to_dict_uses_empty_config_on_invalid_json() -> None:
    data = preset_row_to_dict({"config_json": "{bad", "is_system": 0, "is_default": 0}, include_config=True)

    assert data["config_json"] == {}
