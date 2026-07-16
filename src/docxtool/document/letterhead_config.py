"""Validation and normalization for the optional managed letterhead config."""

from __future__ import annotations

import copy
import unicodedata

from docxtool.document.style_config import ConfigValidationError


DOCUMENT_DIRECTIONS = {"upward", "downward", "parallel"}
ISSUANCE_MODES = {"single", "joint"}
MARK_DISPLAY_MODES = {"agency_with_document", "agency_only"}
JOINT_MARK_SCOPES = {"all_agencies", "sponsor_only"}
EXISTING_POLICIES = {"preserve_external"}

MAX_AGENCIES = 10
MAX_AGENCY_NAME = 80
MAX_SIGNERS_PER_AGENCY = 10
MAX_SIGNER_NAME = 30
MAX_AGENCY_CODE = 40
MAX_TOTAL_CHARACTERS = 2000
MAX_ORDER_VALUE = 1_000_000


def default_letterhead_config() -> dict:
    return {
        "schema_version": 1,
        "enabled": False,
        "document_direction": "downward",
        "issuance_mode": "single",
        "mark_display_mode": "agency_with_document",
        "joint_mark_scope": "all_agencies",
        "agencies": [
            {
                "id": "agency-1",
                "name": "",
                "short_name": "",
                "role": "sponsor",
                "order": 1,
            }
        ],
        "document_number": {"agency_code": "", "year": None, "sequence": None},
        "signers": [],
        "existing_policy": "preserve_external",
        "replace_managed": False,
        "layout_version": 1,
    }


def _error(field: str, reason: str):
    raise ConfigValidationError(field, reason)


def _object(field: str, value) -> dict:
    if not isinstance(value, dict):
        _error(field, "必须是对象")
    return value


def _list(field: str, value) -> list:
    if not isinstance(value, list):
        _error(field, "必须是数组")
    return value


def _strict_bool(field: str, value) -> bool:
    if not isinstance(value, bool):
        _error(field, "必须是布尔值")
    return value


def _strict_int(field: str, value, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _error(field, "必须是整数")
    if value < minimum or value > maximum:
        _error(field, f"必须在 {minimum} 到 {maximum} 之间")
    return value


def _enum(field: str, value, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        _error(field, f"必须是 {', '.join(sorted(allowed))} 之一")
    return value


def _has_control(value: str) -> bool:
    return any(ch in "\r\n" or unicodedata.category(ch) == "Cc" for ch in value)


def _text(field: str, value, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        _error(field, "必须是字符串")
    normalized = value.strip()
    if required and not normalized:
        _error(field, "不能为空")
    if len(normalized) > maximum:
        _error(field, f"不得超过 {maximum} 个字符")
    if _has_control(normalized):
        _error(field, "不得包含换行或控制字符")
    return normalized


def normalize_letterhead_config(value) -> dict:
    """Validate and return a privacy-safe normalized copy.

    ``None`` is treated as a missing optional section. Disabled configurations
    keep placeholder fields but do not require names or document-number values.
    """

    if value is None:
        return default_letterhead_config()
    raw = copy.deepcopy(_object("letterhead", value))
    schema_version = _strict_int(
        "letterhead.schema_version", raw.get("schema_version", 1), 1, 1
    )
    enabled = _strict_bool("letterhead.enabled", raw.get("enabled", False))
    direction = _enum(
        "letterhead.document_direction",
        raw.get("document_direction", "downward"),
        DOCUMENT_DIRECTIONS,
    )
    issuance_mode = _enum(
        "letterhead.issuance_mode", raw.get("issuance_mode", "single"), ISSUANCE_MODES
    )
    mark_display_mode = _enum(
        "letterhead.mark_display_mode",
        raw.get("mark_display_mode", "agency_with_document"),
        MARK_DISPLAY_MODES,
    )
    joint_mark_scope = _enum(
        "letterhead.joint_mark_scope",
        raw.get("joint_mark_scope", "all_agencies"),
        JOINT_MARK_SCOPES,
    )
    existing_policy = _enum(
        "letterhead.existing_policy",
        raw.get("existing_policy", "preserve_external"),
        EXISTING_POLICIES,
    )
    replace_managed = _strict_bool(
        "letterhead.replace_managed", raw.get("replace_managed", False)
    )
    layout_version = _strict_int(
        "letterhead.layout_version", raw.get("layout_version", 1), 1, 1
    )

    agency_items = _list("letterhead.agencies", raw.get("agencies", []))
    if len(agency_items) > MAX_AGENCIES:
        _error("letterhead.agencies", f"最多允许 {MAX_AGENCIES} 个机关")
    agencies = []
    agency_ids: set[str] = set()
    agency_orders: set[int] = set()
    sponsor_count = 0
    total_characters = 0
    for index, item in enumerate(agency_items):
        item = _object(f"letterhead.agencies[{index}]", item)
        agency_id = _text(
            f"letterhead.agencies[{index}].id", item.get("id", ""), 64, required=True
        )
        if agency_id in agency_ids:
            _error(f"letterhead.agencies[{index}].id", "机关 ID 必须唯一")
        agency_ids.add(agency_id)
        name = _text(
            f"letterhead.agencies[{index}].name",
            item.get("name", ""),
            MAX_AGENCY_NAME,
            required=enabled,
        )
        short_name = _text(
            f"letterhead.agencies[{index}].short_name",
            item.get("short_name", ""),
            MAX_AGENCY_NAME,
        )
        role = _enum(
            f"letterhead.agencies[{index}].role",
            item.get("role", "joint"),
            {"sponsor", "joint"},
        )
        order = _strict_int(
            f"letterhead.agencies[{index}].order", item.get("order"), 1, MAX_ORDER_VALUE
        )
        if order in agency_orders:
            _error(f"letterhead.agencies[{index}].order", "机关 order 必须唯一")
        agency_orders.add(order)
        sponsor_count += role == "sponsor"
        total_characters += len(name) + len(short_name)
        agencies.append(
            {
                "id": agency_id,
                "name": name,
                "short_name": short_name,
                "role": role,
                "order": order,
            }
        )

    if enabled:
        if issuance_mode == "single" and len(agencies) != 1:
            _error("letterhead.agencies", "单一机关发文必须且只能配置一个机关")
        if issuance_mode == "joint" and len(agencies) < 2:
            _error("letterhead.agencies", "联合发文至少需要两个机关")
        if sponsor_count != 1:
            _error("letterhead.agencies", "必须且只能有一个主办机关")

    agencies.sort(key=lambda item: (item["role"] != "sponsor", item["order"]))
    for order, agency in enumerate(agencies, 1):
        agency["order"] = order

    number = _object("letterhead.document_number", raw.get("document_number", {}))
    agency_code = _text(
        "letterhead.document_number.agency_code",
        number.get("agency_code", ""),
        MAX_AGENCY_CODE,
        required=enabled,
    )
    if any(char in agency_code for char in "〔〕第"):
        _error("letterhead.document_number.agency_code", "不得包含六角括号或“第”字")
    year = number.get("year")
    sequence = number.get("sequence")
    if year is not None:
        year = _strict_int("letterhead.document_number.year", year, 1900, 2100)
    if sequence is not None:
        sequence = _strict_int("letterhead.document_number.sequence", sequence, 1, 999999)
    if enabled and year is None:
        _error("letterhead.document_number.year", "启用版头时不能为空")
    if enabled and sequence is None:
        _error("letterhead.document_number.sequence", "启用版头时不能为空")
    total_characters += len(agency_code)

    signer_items = _list("letterhead.signers", raw.get("signers", []))
    signers = []
    signer_ids: set[str] = set()
    signer_orders: dict[str, set[int]] = {}
    signer_counts: dict[str, int] = {}
    for index, item in enumerate(signer_items):
        item = _object(f"letterhead.signers[{index}]", item)
        signer_id = _text(
            f"letterhead.signers[{index}].id", item.get("id", ""), 64, required=True
        )
        if signer_id in signer_ids:
            _error(f"letterhead.signers[{index}].id", "签发人 ID 必须唯一")
        signer_ids.add(signer_id)
        agency_id = _text(
            f"letterhead.signers[{index}].agency_id",
            item.get("agency_id", ""),
            64,
            required=True,
        )
        if agency_id not in agency_ids:
            _error(f"letterhead.signers[{index}].agency_id", "必须对应有效机关")
        name = _text(
            f"letterhead.signers[{index}].name",
            item.get("name", ""),
            MAX_SIGNER_NAME,
            required=True,
        )
        label = _text(
            f"letterhead.signers[{index}].label",
            item.get("label", "签发人"),
            20,
            required=True,
        )
        order = _strict_int(
            f"letterhead.signers[{index}].order", item.get("order"), 1, MAX_ORDER_VALUE
        )
        orders = signer_orders.setdefault(agency_id, set())
        if order in orders:
            _error(f"letterhead.signers[{index}].order", "同一机关的签发人 order 必须唯一")
        orders.add(order)
        signer_counts[agency_id] = signer_counts.get(agency_id, 0) + 1
        if signer_counts[agency_id] > MAX_SIGNERS_PER_AGENCY:
            _error(
                f"letterhead.signers[{index}].agency_id",
                f"每个机关最多允许 {MAX_SIGNERS_PER_AGENCY} 个签发人",
            )
        total_characters += len(name) + len(label)
        signers.append(
            {
                "id": signer_id,
                "agency_id": agency_id,
                "name": name,
                "label": label,
                "order": order,
            }
        )

    agency_order = {item["id"]: item["order"] for item in agencies}
    signers.sort(key=lambda item: (agency_order.get(item["agency_id"], MAX_AGENCIES + 1), item["order"]))
    if enabled and direction == "upward":
        required_agencies = agencies if issuance_mode == "joint" else agencies[:1]
        missing = [agency["id"] for agency in required_agencies if not signer_counts.get(agency["id"])]
        if missing:
            _error("letterhead.signers", "上行文必须为每个发文机关配置至少一个签发人")

    if total_characters > MAX_TOTAL_CHARACTERS:
        _error("letterhead", f"总字符数不得超过 {MAX_TOTAL_CHARACTERS}")

    return {
        "schema_version": schema_version,
        "enabled": enabled,
        "document_direction": direction,
        "issuance_mode": issuance_mode,
        "mark_display_mode": mark_display_mode,
        "joint_mark_scope": joint_mark_scope,
        "agencies": agencies,
        "document_number": {
            "agency_code": agency_code,
            "year": year,
            "sequence": sequence,
        },
        "signers": signers,
        "existing_policy": existing_policy,
        "replace_managed": replace_managed,
        "layout_version": layout_version,
    }


__all__ = ["default_letterhead_config", "normalize_letterhead_config"]
