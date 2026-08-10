from io import StringIO
import json
import logging
import sys

import pytest

from docxtool.document import style_config
from docxtool.paths import default_format_config_path
from docxtool.document.style_config import (
    ConfigValidationError,
    load_rules_and_settings,
    validate_format_config,
)


def _page_number(config: dict) -> dict:
    return load_rules_and_settings(config)[2]["page_number"]


def test_console_logging_splits_normal_and_problem_levels(monkeypatch) -> None:
    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    logger = logging.Logger("docx_tool_console_test", logging.DEBUG)
    logger.propagate = False

    style_config._ensure_console_handler(logger)
    style_config._ensure_console_handler(logger)
    logger.debug("debug-message")
    logger.info("info-message")
    logger.warning("warning-message")
    logger.error("error-message")
    logger.critical("critical-message")

    console_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
    ]
    assert len(console_handlers) == 2
    assert "debug-message" in stdout.getvalue()
    assert "info-message" in stdout.getvalue()
    assert "warning-message" not in stdout.getvalue()
    assert "error-message" not in stdout.getvalue()
    assert "warning-message" in stderr.getvalue()
    assert "error-message" in stderr.getvalue()
    assert "critical-message" in stderr.getvalue()
    assert "info-message" not in stderr.getvalue()


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


def test_missing_signature_block_preserves_legacy_layout() -> None:
    assert load_rules_and_settings({})[2]["signature_block"] == {"mode": "preserve"}


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, "structural"),
        ({"mode": "smart"}, "structural"),
        ({"processing_mode": "strict"}, "strict"),
        ({"processing": {"strategy": "normalize"}}, "normalize"),
    ],
)
def test_processing_mode_is_normalized_to_an_explicit_strategy(
    config: dict, expected: str
) -> None:
    assert load_rules_and_settings(config)[2]["processing"] == {"strategy": expected}


def test_invalid_processing_mode_is_rejected() -> None:
    with pytest.raises(ConfigValidationError) as error:
        validate_format_config({"processing_mode": "rewrite-everything"})

    assert error.value.field == "processing.mode"


def test_default_format_uses_without_seal_signature_layout() -> None:
    config = json.loads(default_format_config_path().read_text(encoding="utf-8"))

    assert load_rules_and_settings(config)[2]["signature_block"] == {
        "mode": "without_seal"
    }


def test_signature_block_mode_uses_existing_config_validation_error() -> None:
    with pytest.raises(ConfigValidationError) as error:
        validate_format_config({"signature_block": {"mode": "guess"}})

    assert error.value.field == "signature_block.mode"
