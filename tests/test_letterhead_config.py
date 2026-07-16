import copy
import json

import pytest

from docxtool.document.letterhead_config import (
    default_letterhead_config,
    normalize_letterhead_config,
)
from docxtool.document.style_config import ConfigValidationError, validate_format_config
from docxtool.paths import default_format_config_path


def enabled_config(**changes):
    config = default_letterhead_config()
    config.update(
        {
            "enabled": True,
            "agencies": [
                {
                    "id": "agency-1",
                    "name": "测试机关",
                    "short_name": "测试机关",
                    "role": "sponsor",
                    "order": 1,
                }
            ],
            "document_number": {"agency_code": "测发", "year": 2026, "sequence": 12},
        }
    )
    config.update(changes)
    return config


def test_default_format_and_optional_section_are_backward_compatible():
    default_config = json.loads(default_format_config_path().read_text(encoding="utf-8"))
    validated = validate_format_config(default_config)
    assert validated["letterhead"]["enabled"] is False
    assert validated["letterhead"]["document_number"] == {
        "agency_code": "",
        "year": None,
        "sequence": None,
    }

    without = copy.deepcopy(default_config)
    without.pop("letterhead")
    assert "letterhead" not in validate_format_config(without)
    with_null = copy.deepcopy(default_config)
    with_null["letterhead"] = None
    assert validate_format_config(with_null)["letterhead"] is None
    assert normalize_letterhead_config(None)["enabled"] is False


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"enabled": "true"}, "letterhead.enabled"),
        ({"schema_version": 2}, "letterhead.schema_version"),
        ({"document_direction": "sideways"}, "letterhead.document_direction"),
        ({"issuance_mode": "group"}, "letterhead.issuance_mode"),
        ({"existing_policy": "replace_all"}, "letterhead.existing_policy"),
    ],
)
def test_rejects_invalid_scalar_fields(patch, field):
    config = enabled_config(**patch)
    with pytest.raises(ConfigValidationError) as exc_info:
        normalize_letterhead_config(config)
    assert exc_info.value.field == field
    assert exc_info.value.code == "FORMAT_CONFIG_INVALID"


def test_single_joint_sponsor_id_and_order_rules():
    second = {"id": "agency-2", "name": "联合机关", "short_name": "", "role": "joint", "order": 2}
    cases = [
        (enabled_config(agencies=enabled_config()["agencies"] + [second]), "letterhead.agencies"),
        (enabled_config(issuance_mode="joint"), "letterhead.agencies"),
        (enabled_config(agencies=[{**enabled_config()["agencies"][0], "role": "joint"}]), "letterhead.agencies"),
        (enabled_config(agencies=[enabled_config()["agencies"][0], {**second, "role": "sponsor"}]), "letterhead.agencies"),
        (enabled_config(issuance_mode="joint", agencies=[enabled_config()["agencies"][0], {**second, "id": "agency-1"}]), "letterhead.agencies[1].id"),
        (enabled_config(issuance_mode="joint", agencies=[enabled_config()["agencies"][0], {**second, "order": 1}]), "letterhead.agencies[1].order"),
    ]
    for config, field in cases:
        with pytest.raises(ConfigValidationError) as exc_info:
            normalize_letterhead_config(config)
        assert exc_info.value.field == field


def test_joint_agencies_and_signers_are_sorted_and_preserved():
    agencies = [
        {"id": "agency-2", "name": "联合机关", "short_name": "", "role": "joint", "order": 1},
        {"id": "agency-1", "name": "主办机关", "short_name": "", "role": "sponsor", "order": 2},
    ]
    signers = [
        {"id": "signer-2", "agency_id": "agency-2", "name": "李四", "label": "签发人", "order": 1},
        {"id": "signer-1", "agency_id": "agency-1", "name": "张三", "label": "签发人", "order": 1},
        {"id": "signer-3", "agency_id": "agency-1", "name": "王五", "label": "签发人", "order": 2},
    ]
    normalized = normalize_letterhead_config(
        enabled_config(
            issuance_mode="joint",
            document_direction="upward",
            agencies=agencies,
            signers=signers,
        )
    )
    assert [agency["id"] for agency in normalized["agencies"]] == ["agency-1", "agency-2"]
    assert [agency["order"] for agency in normalized["agencies"]] == [1, 2]
    assert [signer["id"] for signer in normalized["signers"]] == ["signer-1", "signer-3", "signer-2"]


def test_upward_requires_signer_for_each_agency_and_rejects_unknown_agency():
    with pytest.raises(ConfigValidationError) as missing:
        normalize_letterhead_config(enabled_config(document_direction="upward"))
    assert missing.value.field == "letterhead.signers"

    config = enabled_config(
        document_direction="upward",
        signers=[
            {"id": "signer-1", "agency_id": "missing", "name": "张三", "label": "签发人", "order": 1}
        ],
    )
    with pytest.raises(ConfigValidationError) as unknown:
        normalize_letterhead_config(config)
    assert unknown.value.field == "letterhead.signers[0].agency_id"


@pytest.mark.parametrize(
    ("document_number", "field"),
    [
        ({"agency_code": "测〔发", "year": 2026, "sequence": 1}, "letterhead.document_number.agency_code"),
        ({"agency_code": "测\n发", "year": 2026, "sequence": 1}, "letterhead.document_number.agency_code"),
        ({"agency_code": "测发", "year": 1899, "sequence": 1}, "letterhead.document_number.year"),
        ({"agency_code": "测发", "year": 2026, "sequence": 0}, "letterhead.document_number.sequence"),
    ],
)
def test_document_number_validation(document_number, field):
    with pytest.raises(ConfigValidationError) as exc_info:
        normalize_letterhead_config(enabled_config(document_number=document_number))
    assert exc_info.value.field == field


def test_limits_agencies_signers_names_and_total_characters():
    too_many = [
        {"id": f"agency-{index}", "name": f"机关{index}", "short_name": "", "role": "sponsor" if index == 1 else "joint", "order": index}
        for index in range(1, 12)
    ]
    with pytest.raises(ConfigValidationError) as agencies_error:
        normalize_letterhead_config(enabled_config(issuance_mode="joint", agencies=too_many))
    assert agencies_error.value.field == "letterhead.agencies"

    with pytest.raises(ConfigValidationError) as name_error:
        normalize_letterhead_config(
            enabled_config(agencies=[{**enabled_config()["agencies"][0], "name": "机" * 81}])
        )
    assert name_error.value.field == "letterhead.agencies[0].name"

    signers = [
        {
            "id": f"signer-{index}",
            "agency_id": "agency-1",
            "name": f"姓名{index}",
            "label": "签发人",
            "order": index,
        }
        for index in range(1, 12)
    ]
    with pytest.raises(ConfigValidationError) as signer_count_error:
        normalize_letterhead_config(enabled_config(signers=signers))
    assert signer_count_error.value.field == "letterhead.signers[10].agency_id"

    with pytest.raises(ConfigValidationError) as signer_name_error:
        normalize_letterhead_config(
            enabled_config(
                signers=[
                    {
                        "id": "signer-1",
                        "agency_id": "agency-1",
                        "name": "名" * 31,
                        "label": "签发人",
                        "order": 1,
                    }
                ]
            )
        )
    assert signer_name_error.value.field == "letterhead.signers[0].name"

    agencies = [
        {
            "id": f"agency-{index}",
            "name": "机关" * 40,
            "short_name": "简称" * 40,
            "role": "sponsor" if index == 1 else "joint",
            "order": index,
        }
        for index in range(1, 11)
    ]
    many_signers = [
        {
            "id": f"signer-{agency}-{index}",
            "agency_id": f"agency-{agency}",
            "name": "姓名" * 15,
            "label": "签发人",
            "order": index,
        }
        for agency in range(1, 11)
        for index in range(1, 11)
    ]
    with pytest.raises(ConfigValidationError) as total_error:
        normalize_letterhead_config(
            enabled_config(issuance_mode="joint", agencies=agencies, signers=many_signers)
        )
    assert total_error.value.field == "letterhead"


def test_signer_ids_and_orders_must_be_unique_per_rules():
    first = {
        "id": "signer-1",
        "agency_id": "agency-1",
        "name": "张三",
        "label": "签发人",
        "order": 1,
    }
    with pytest.raises(ConfigValidationError) as duplicate_id:
        normalize_letterhead_config(
            enabled_config(signers=[first, {**first, "name": "李四", "order": 2}])
        )
    assert duplicate_id.value.field == "letterhead.signers[1].id"

    with pytest.raises(ConfigValidationError) as duplicate_order:
        normalize_letterhead_config(
            enabled_config(signers=[first, {**first, "id": "signer-2", "name": "李四"}])
        )
    assert duplicate_order.value.field == "letterhead.signers[1].order"


def test_letterhead_must_be_an_object():
    with pytest.raises(ConfigValidationError) as exc_info:
        normalize_letterhead_config([])
    assert exc_info.value.field == "letterhead"
