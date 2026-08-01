from __future__ import annotations

import base64
import json

import pytest

from docxtool.paths import default_format_config_path
from docxtool.web import app as server
from docxtool.web.format_request import (
    FormatConfigRequestError,
    decode_format_config,
    processing_strategy_from_mode,
    upload_request_meta,
    validate_requested_processing_mode,
)


def _format_config_headers(config: dict) -> dict[str, str]:
    raw = json.dumps(config, ensure_ascii=False).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return {
        "X-Format-Config": encoded,
        "X-Format-Config-Encoding": "base64url-json",
    }


def test_format_request_decodes_default_config_and_matches_app_facade():
    data = json.loads(default_format_config_path().read_text(encoding="utf-8"))
    headers = _format_config_headers(data)

    decoded = decode_format_config(headers, max_header_bytes=96 * 1024, max_json_bytes=64 * 1024)

    assert decoded == data
    assert server._decode_format_config(headers) == decoded


def test_format_request_rejects_invalid_config_with_stable_error():
    headers = _format_config_headers({"styles": [], "page": {"width_cm": "NaN"}})

    with pytest.raises(FormatConfigRequestError) as error:
        decode_format_config(headers, max_header_bytes=96 * 1024, max_json_bytes=64 * 1024)

    assert error.value.code == "FORMAT_CONFIG_INVALID"
    assert error.value.field == "page.width_cm"
    assert error.value.status == 400


def test_format_request_upload_meta_and_processing_mode_validation():
    meta = upload_request_meta(
        {
            "X-Processing-Mode": "smart",
            "X-Preset-Id": "preset-1",
            "X-Preset-Name": "%E6%A0%87%E5%87%86",
            "X-Template-Type": "official",
        }
    )

    assert meta["processing_mode"] == "smart"
    assert meta["preset_name"] == "标准"
    assert processing_strategy_from_mode("smart") == "structural"
    validate_requested_processing_mode({"processing": {"strategy": "structural"}}, meta)
    assert meta["processing_strategy"] == "structural"

    with pytest.raises(FormatConfigRequestError) as error:
        validate_requested_processing_mode({"processing": {"strategy": "strict"}}, {"processing_mode": "smart"})
    assert error.value.code == "PROCESSING_MODE_CONFLICT"
