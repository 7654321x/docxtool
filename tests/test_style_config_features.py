import pytest

from docxtool.document.style_config import (
    ConfigValidationError,
    load_rules_and_settings,
    validate_format_config,
)


def _page_number(config: dict) -> dict:
    return load_rules_and_settings(config)[2]["page_number"]


def test_page_number_defaults_are_standard_document_defaults() -> None:
    page_number = _page_number({})

    assert page_number == {
        "enabled": True,
        "font_name": "宋体",
        "font_size_pt": 14,
        "bold": False,
        "style": "dash",
        "position": "outside",
        "first_page": True,
        "section_numbering": "continue",
        "offset_from_text_mm": 7,
    }


def test_canonical_page_number_enabled_takes_precedence_over_legacy_flag() -> None:
    page_number = _page_number(
        {
            "features": {"page_number_enabled": True},
            "page_number": {"enabled": False},
        }
    )

    assert page_number["enabled"] is False


@pytest.mark.parametrize("legacy_enabled", [True, False])
def test_legacy_page_number_enabled_is_used_only_when_canonical_value_is_missing(
    legacy_enabled: bool,
) -> None:
    page_number = _page_number({"features": {"page_number_enabled": legacy_enabled}})

    assert page_number["enabled"] is legacy_enabled


@pytest.mark.parametrize(
    ("config", "field"),
    [
        ({"page_number": {"font_name": ""}}, "page_number.font_name"),
        ({"page_number": {"font_size_pt": 0}}, "page_number.font_size_pt"),
        ({"page_number": {"bold": "false"}}, "page_number.bold"),
        ({"page_number": {"enabled": 1}}, "page_number.enabled"),
    ],
)
def test_page_number_fields_use_existing_config_validation_errors(
    config: dict, field: str
) -> None:
    with pytest.raises(ConfigValidationError) as error:
        validate_format_config(config)

    assert error.value.field == field
