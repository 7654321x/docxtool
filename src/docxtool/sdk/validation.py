"""JSON Schema loading and public SDK validation helpers."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, Mapping, Sequence

try:  # Python 3.9+
    from importlib.resources import files
except ImportError:  # pragma: no cover - exercised on Python 3.8
    from importlib_resources import files

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from .constants import (
    BINDING_PRECONDITION_FIELDS,
    HOST_SNAPSHOT_SCHEMA_VERSION,
    HOST_SNAPSHOT_SUMMARY_SCHEMA_VERSION,
    HOST_TEXT_CONTRACT_VERSION,
    INTEGRATION_CONTRACT_VERSION,
    OFFSET_ENCODING,
    RECOGNITION_BINDING_SCHEMA_VERSION,
    RECOGNITION_PLAN_SCHEMA_VERSION,
    RECOGNITION_REQUEST_SCHEMA_VERSION,
    SCHEMA_FILENAMES,
    SDK_ERROR_SCHEMA_VERSION,
    SDK_MANIFEST_SCHEMA_VERSION,
    SOURCE_LOCATOR_VERSION,
    VALIDATION_REPORT_SCHEMA_VERSION,
)
from .errors import (
    DocxToolSdkError,
    InvalidHostSnapshotError,
    InvalidRecognitionBindingError,
    InvalidRecognitionPlanError,
    InvalidRequestError,
)
from .manifest import get_sdk_manifest
from .models import (
    HostSnapshot,
    HostSnapshotSummary,
    RecognitionBinding,
    RecognitionPlan,
    RecognitionRequest,
    ValidationIssue,
    ValidationReport,
    _host_snapshot_from_dict_unchecked,
    _recognition_binding_from_dict_unchecked,
    _recognition_plan_from_dict_unchecked,
    _recognition_request_from_dict_unchecked,
    stable_id,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_PATH_TOKENS = {
    "text",
    "raw_text",
    "recognized_text",
    "raw_fragment_text",
    "canonical_fragment_text",
}
_DETAIL_ALLOWLIST = {
    "actual_type",
    "code",
    "count",
    "expected",
    "field",
    "index",
    "issue_code",
    "object_kind",
    "path",
    "reason",
    "recommended_action",
    "schema_name",
    "schema_version",
    "severity",
    "status",
    "supported",
    "validator",
}


def _safe_detail(details: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    if not details:
        return {}
    safe: Dict[str, Any] = {}
    for key, value in details.items():
        if key not in _DETAIL_ALLOWLIST:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            safe[key] = [
                item for item in value if isinstance(item, (str, int, float, bool)) or item is None
            ]
    return safe


def _issue(
    code: str,
    path: str,
    severity: str,
    details: Mapping[str, Any] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        path=path or "$",
        severity=severity,
        detail=_safe_detail({"path": path or "$", **dict(details or {})}),
    )


def _path(items: Iterable[Any]) -> str:
    value = "$"
    for item in items:
        if isinstance(item, int):
            value += "[{0}]".format(item)
        else:
            value += ".{0}".format(item)
    return value


def get_json_schema(schema_name: str) -> Dict[str, Any]:
    """Load an installed public SDK JSON Schema by stable name or version."""
    aliases = {
        "manifest": SDK_MANIFEST_SCHEMA_VERSION,
        "sdk-manifest": SDK_MANIFEST_SCHEMA_VERSION,
        "request": RECOGNITION_REQUEST_SCHEMA_VERSION,
        "recognition-request": RECOGNITION_REQUEST_SCHEMA_VERSION,
        "plan": RECOGNITION_PLAN_SCHEMA_VERSION,
        "recognition-plan": RECOGNITION_PLAN_SCHEMA_VERSION,
        "host-snapshot": HOST_SNAPSHOT_SCHEMA_VERSION,
        "snapshot": HOST_SNAPSHOT_SCHEMA_VERSION,
        "binding": RECOGNITION_BINDING_SCHEMA_VERSION,
        "recognition-binding": RECOGNITION_BINDING_SCHEMA_VERSION,
        "validation-report": VALIDATION_REPORT_SCHEMA_VERSION,
        "report": VALIDATION_REPORT_SCHEMA_VERSION,
        "host-snapshot-summary": HOST_SNAPSHOT_SUMMARY_SCHEMA_VERSION,
        "snapshot-summary": HOST_SNAPSHOT_SUMMARY_SCHEMA_VERSION,
        "error": SDK_ERROR_SCHEMA_VERSION,
        "sdk-error": SDK_ERROR_SCHEMA_VERSION,
    }
    normalized = schema_name or ""
    if normalized.endswith(".schema.json"):
        normalized = normalized[: -len(".schema.json")]
    schema_version = aliases.get(normalized, normalized)
    filename = SCHEMA_FILENAMES.get(schema_version)
    if not filename:
        raise DocxToolSdkError(
            "未知 schema",
            code="UNSUPPORTED_SCHEMA_VERSION",
            details={"schema_name": schema_name, "path": "schema_name"},
        )
    schema_path = files("docxtool.resources.schemas").joinpath(filename)
    return json.loads(schema_path.read_text(encoding="utf-8"))


def load_json_schema(schema_version: str) -> Dict[str, Any]:
    """Backward-compatible schema loader."""
    return get_json_schema(schema_version)


def _schema_issues(value: Any, schema_name: str, code: str) -> tuple[ValidationIssue, ...]:
    issues = []
    try:
        validator = Draft202012Validator(get_json_schema(schema_name))
        for exc in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path)):
            issues.append(_schema_issue(exc, code))
    except JsonSchemaValidationError as exc:
        issues.append(_schema_issue(exc, code))
    return tuple(issues)


def _schema_issue(exc: JsonSchemaValidationError, code: str) -> ValidationIssue:
    path = _path(exc.absolute_path)
    if exc.validator == "required" and isinstance(exc.message, str) and "'" in exc.message:
        missing = exc.message.split("'", 2)[1]
        path = ".".join((path, missing)) if path != "$" else "$.{0}".format(missing)
    issue_code = code
    if exc.validator == "const":
        if path.endswith("schema_version") or path.endswith("source_locator_version"):
            issue_code = "UNSUPPORTED_SCHEMA_VERSION"
        elif path.endswith("integration_contract_version"):
            issue_code = "UNSUPPORTED_INTEGRATION_CONTRACT"
        elif path.endswith("host_text_contract_version") or path.endswith("text_contract_version"):
            issue_code = "UNSUPPORTED_HOST_TEXT_CONTRACT"
        elif path.endswith("offset_encoding") or path.endswith("encoding"):
            issue_code = "UNSUPPORTED_OFFSET_ENCODING"
    actual_type = type(exc.instance).__name__
    return _issue(
        issue_code,
        path,
        "error",
        {"validator": str(exc.validator), "actual_type": actual_type},
    )


def _root_unknowns(
    value: Mapping[str, Any],
    known: set[str],
    code: str,
    *,
    strict: bool,
) -> tuple[ValidationIssue, ...]:
    issues = []
    severity = "error" if strict else "warning"
    for field in sorted(set(value) - known):
        issues.append(_issue(code, "$.{0}".format(field), severity, {"field": field, "reason": "unknown_field"}))
    return tuple(issues)


def _resolve_schema(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return schema
    target: Any = root
    for part in ref[2:].split("/"):
        target = target[part]
    return target if isinstance(target, Mapping) else schema


def _schema_field_policy_issues(
    value: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    code: str,
    *,
    strict: bool,
    path: str = "$",
) -> tuple[ValidationIssue, ...]:
    schema = _resolve_schema(schema, root)
    issues: list[ValidationIssue] = []
    if isinstance(value, Mapping):
        properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
        if properties:
            severity = "error" if strict else "warning"
            for field in sorted(set(value) - set(properties)):
                issues.append(_issue(
                    code,
                    "{0}.{1}".format(path, field) if path != "$" else "$.{0}".format(field),
                    severity,
                    {"field": str(field), "reason": "unknown_field"},
                ))
            for field, nested_schema in properties.items():
                if field in value and isinstance(nested_schema, Mapping):
                    nested_path = "{0}.{1}".format(path, field) if path != "$" else "$.{0}".format(field)
                    issues.extend(_schema_field_policy_issues(
                        value[field],
                        nested_schema,
                        root,
                        code,
                        strict=strict,
                        path=nested_path,
                    ))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items_schema = schema.get("items")
        if isinstance(items_schema, Mapping):
            for index, item in enumerate(value):
                issues.extend(_schema_field_policy_issues(
                    item,
                    items_schema,
                    root,
                    code,
                    strict=strict,
                    path="{0}[{1}]".format(path, index),
                ))
    return tuple(issues)


def _schema_policy_issues(value: Any, schema_name: str, code: str, *, strict: bool) -> tuple[ValidationIssue, ...]:
    if not isinstance(value, (Mapping, Sequence)) or isinstance(value, (str, bytes, bytearray)):
        return ()
    schema = get_json_schema(schema_name)
    return _schema_field_policy_issues(value, schema, schema, code, strict=strict)


def _report(errors: Iterable[ValidationIssue], warnings: Iterable[ValidationIssue] = ()) -> ValidationReport:
    error_tuple = tuple(errors)
    warning_tuple = tuple(warnings)
    return ValidationReport(valid=not error_tuple, errors=error_tuple, warnings=warning_tuple)


def _raise_if_invalid(report: ValidationReport, error_cls: type[DocxToolSdkError]) -> None:
    if report.valid:
        return
    first = report.errors[0]
    raise error_cls(
        "SDK 协议校验失败: {0}".format(first.path),
        code=first.code,
        details=first.detail,
    )


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.match(value))


def _check_sha(value: Any, path: str, code: str, issues: list[ValidationIssue], *, required: bool = False) -> None:
    if value in (None, "") and not required:
        return
    if not _is_sha256(value):
        issues.append(_issue(code, path, "error", {"reason": "invalid_sha256"}))


def _span_values(span: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (
        span.get("start"),
        span.get("end"),
        span.get("coordinate_system"),
        span.get("encoding"),
    )


def _check_span(
    span: Mapping[str, Any],
    path: str,
    *,
    expected_coordinate: str,
    code: str,
    issues: list[ValidationIssue],
    allow_null: bool = True,
    max_length: int | None = None,
) -> None:
    start, end, coordinate, encoding = _span_values(span)
    if coordinate != expected_coordinate:
        issues.append(_issue(code, path + ".coordinate_system", "error", {"expected": expected_coordinate}))
    if encoding != OFFSET_ENCODING:
        issues.append(_issue(code, path + ".encoding", "error", {"expected": OFFSET_ENCODING}))
    if start is None or end is None:
        if not allow_null or start is not None or end is not None:
            issues.append(_issue(code, path, "error", {"reason": "incomplete_span"}))
        return
    if not isinstance(start, int) or not isinstance(end, int) or start > end:
        issues.append(_issue(code, path, "error", {"reason": "invalid_span"}))
        return
    if max_length is not None and end > max_length:
        issues.append(_issue(code, path, "error", {"reason": "span_out_of_bounds"}))


def _expected_plan_id(payload: Mapping[str, Any]) -> str:
    source = payload.get("source") if isinstance(payload.get("source"), Mapping) else {}
    producer = payload.get("producer") if isinstance(payload.get("producer"), Mapping) else {}
    contracts = payload.get("contracts") if isinstance(payload.get("contracts"), Mapping) else {}
    recognition = payload.get("recognition") if isinstance(payload.get("recognition"), Mapping) else {}
    return stable_id(
        "plan",
        source.get("sha256"),
        payload.get("integration_contract_version"),
        payload.get("schema_version"),
        producer.get("engine_version"),
        producer.get("package_version"),
        contracts.get("source_locator_version"),
        contracts.get("host_text_contract_version"),
        OFFSET_ENCODING,
        recognition.get("processing_mode"),
        recognition.get("recognition_mode"),
        recognition.get("request_digest", ""),
    )


def _expected_physical_group_id(plan_id: str, block: Mapping[str, Any]) -> str:
    locator = block.get("source_locator") if isinstance(block.get("source_locator"), Mapping) else {}
    group_parts = (
        plan_id,
        locator.get("physical_paragraph_index"),
        locator.get("physical_occurrence_index"),
        locator.get("physical_raw_text_sha256"),
    )
    if locator.get("physical_paragraph_index") is None:
        group_parts += (block.get("block_index"),)
    return stable_id("pg", *group_parts)


def _expected_block_id(plan_id: str, block: Mapping[str, Any], physical_group_id: str) -> str:
    locator = block.get("source_locator") if isinstance(block.get("source_locator"), Mapping) else {}
    segment = block.get("segment") if isinstance(block.get("segment"), Mapping) else {}
    semantic = block.get("semantic") if isinstance(block.get("semantic"), Mapping) else {}
    return stable_id(
        "blk",
        plan_id,
        physical_group_id,
        segment.get("index"),
        locator.get("raw_fragment_sha256"),
        locator.get("canonical_fragment_sha256"),
        semantic.get("type_id"),
    )


def _binding_block_id_parts(block: Mapping[str, Any]) -> tuple[Any, ...]:
    binding = block.get("binding") if isinstance(block.get("binding"), Mapping) else {}
    target = block.get("host_target") if isinstance(block.get("host_target"), Mapping) else {}
    raw_span = target.get("raw_span") if isinstance(target.get("raw_span"), Mapping) else {}
    canonical_span = target.get("canonical_span") if isinstance(target.get("canonical_span"), Mapping) else {}
    preconditions = block.get("preconditions") if isinstance(block.get("preconditions"), Mapping) else {}
    stable_preconditions = {
        field: preconditions.get(field)
        for field in BINDING_PRECONDITION_FIELDS
        if field in preconditions
    }
    return (
        block.get("block_id"),
        binding.get("status"),
        binding.get("recommended_action"),
        target.get("host_paragraph_id"),
        target.get("host_paragraph_index"),
        target.get("story_id"),
        target.get("story_type"),
        raw_span.get("start"),
        raw_span.get("end"),
        canonical_span.get("start"),
        canonical_span.get("end"),
        stable_preconditions,
    )


def _binding_group_id_parts(group: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        group.get("physical_group_id"),
        group.get("status"),
        group.get("host_paragraph_id"),
        group.get("host_paragraph_index"),
        tuple(group.get("candidate_host_paragraph_ids", ()) or ()),
        tuple(group.get("warnings", ()) or ()),
    )


def _expected_binding_id(payload: Mapping[str, Any]) -> str:
    host = payload.get("host") if isinstance(payload.get("host"), Mapping) else {}
    contracts = payload.get("contracts") if isinstance(payload.get("contracts"), Mapping) else {}
    blocks = tuple(item for item in payload.get("blocks", ()) if isinstance(item, Mapping))
    physical = tuple(item for item in payload.get("physical_paragraphs", ()) if isinstance(item, Mapping))
    return stable_id(
        "bind",
        payload.get("plan_id"),
        payload.get("snapshot_id"),
        payload.get("source_sha256"),
        payload.get("document_identity"),
        payload.get("document_revision"),
        host.get("kind", payload.get("host_type")),
        contracts.get("host_text_contract_version"),
        contracts.get("offset_encoding"),
        [_binding_block_id_parts(item) for item in blocks],
        [_binding_group_id_parts(item) for item in physical],
    )


def validate_sdk_manifest(value: Mapping[str, Any] | None = None, *, strict: bool = False) -> ValidationReport:
    payload = get_sdk_manifest().to_dict() if value is None else dict(value)
    errors = list(_schema_issues(payload, SDK_MANIFEST_SCHEMA_VERSION, "INVALID_RECOGNITION_REQUEST"))
    warnings: list[ValidationIssue] = []
    unknowns = _schema_policy_issues(payload, SDK_MANIFEST_SCHEMA_VERSION, "INVALID_RECOGNITION_REQUEST", strict=strict)
    if strict:
        errors.extend(unknowns)
    else:
        warnings.extend(unknowns)
    return _report(errors, warnings)


def validate_recognition_request(
    value: RecognitionRequest | Mapping[str, Any],
    *,
    strict: bool = False,
) -> ValidationReport:
    payload = value.to_dict() if isinstance(value, RecognitionRequest) else dict(value) if isinstance(value, Mapping) else value
    errors = list(_schema_issues(payload, RECOGNITION_REQUEST_SCHEMA_VERSION, "INVALID_RECOGNITION_REQUEST"))
    warnings: list[ValidationIssue] = []
    if isinstance(payload, Mapping):
        unknowns = _schema_policy_issues(
            payload,
            RECOGNITION_REQUEST_SCHEMA_VERSION,
            "INVALID_RECOGNITION_REQUEST",
            strict=strict,
        )
        if strict:
            errors.extend(unknowns)
        else:
            warnings.extend(unknowns)
        if payload.get("include_raw_text") is True and payload.get("include_text") is False:
            warnings.append(_issue(
                "PRIVACY_POLICY_VIOLATION",
                "$.include_raw_text",
                "warning",
                {"reason": "raw_text_implies_text"},
            ))
    return _report(errors, warnings)


def validate_sdk_error(value: Mapping[str, Any]) -> ValidationReport:
    payload = dict(value)
    return _report(_schema_issues(payload, SDK_ERROR_SCHEMA_VERSION, "RECOGNITION_FAILED"))


def validate_validation_report(value: ValidationReport | Mapping[str, Any], *, strict: bool = False) -> ValidationReport:
    payload = value.to_dict() if isinstance(value, ValidationReport) else dict(value) if isinstance(value, Mapping) else value
    errors = list(_schema_issues(payload, VALIDATION_REPORT_SCHEMA_VERSION, "INVALID_VALIDATION_REPORT"))
    warnings: list[ValidationIssue] = []
    if isinstance(payload, Mapping):
        unknowns = _schema_policy_issues(payload, VALIDATION_REPORT_SCHEMA_VERSION, "INVALID_VALIDATION_REPORT", strict=strict)
        if strict:
            errors.extend(unknowns)
        else:
            warnings.extend(unknowns)
    return _report(errors, warnings)


def validate_host_snapshot_summary(
    value: HostSnapshotSummary | Mapping[str, Any],
    *,
    strict: bool = False,
) -> ValidationReport:
    payload = value.to_dict() if isinstance(value, HostSnapshotSummary) else dict(value) if isinstance(value, Mapping) else value
    errors = list(_schema_issues(payload, HOST_SNAPSHOT_SUMMARY_SCHEMA_VERSION, "INVALID_HOST_SNAPSHOT_SUMMARY"))
    warnings: list[ValidationIssue] = []
    if isinstance(payload, Mapping):
        unknowns = _schema_policy_issues(
            payload,
            HOST_SNAPSHOT_SUMMARY_SCHEMA_VERSION,
            "INVALID_HOST_SNAPSHOT_SUMMARY",
            strict=strict,
        )
        if strict:
            errors.extend(unknowns)
        else:
            warnings.extend(unknowns)
    return _report(errors, warnings)


def validate_recognition_plan(
    value: RecognitionPlan | Mapping[str, Any],
    *,
    strict: bool = False,
) -> ValidationReport:
    payload = value.to_dict() if isinstance(value, RecognitionPlan) else dict(value) if isinstance(value, Mapping) else value
    errors = list(_schema_issues(payload, RECOGNITION_PLAN_SCHEMA_VERSION, "INVALID_RECOGNITION_PLAN"))
    warnings: list[ValidationIssue] = []
    if isinstance(payload, Mapping):
        unknowns = _schema_policy_issues(
            payload,
            RECOGNITION_PLAN_SCHEMA_VERSION,
            "INVALID_RECOGNITION_PLAN",
            strict=strict,
        )
        if strict:
            errors.extend(unknowns)
        else:
            warnings.extend(unknowns)
    if not errors and isinstance(payload, Mapping):
        errors.extend(_semantic_plan_issues(payload))
    return _report(errors, warnings)


def _semantic_plan_issues(payload: Mapping[str, Any]) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    source = payload.get("source") if isinstance(payload.get("source"), Mapping) else {}
    contracts = payload.get("contracts") if isinstance(payload.get("contracts"), Mapping) else {}
    _check_sha(source.get("sha256"), "$.source.sha256", "INVALID_RECOGNITION_PLAN", issues, required=True)
    if payload.get("integration_contract_version") != INTEGRATION_CONTRACT_VERSION:
        issues.append(_issue("UNSUPPORTED_INTEGRATION_CONTRACT", "$.integration_contract_version", "error"))
    if contracts.get("source_locator_version") != SOURCE_LOCATOR_VERSION:
        issues.append(_issue("UNSUPPORTED_SCHEMA_VERSION", "$.contracts.source_locator_version", "error"))
    if contracts.get("host_text_contract_version") != HOST_TEXT_CONTRACT_VERSION:
        issues.append(_issue("UNSUPPORTED_HOST_TEXT_CONTRACT", "$.contracts.host_text_contract_version", "error"))
    if contracts.get("offset_encoding") != OFFSET_ENCODING:
        issues.append(_issue("UNSUPPORTED_OFFSET_ENCODING", "$.contracts.offset_encoding", "error"))
    expected_plan_id = _expected_plan_id(payload)
    if payload.get("plan_id") != expected_plan_id:
        issues.append(_issue(
            "INVALID_RECOGNITION_PLAN",
            "$.plan_id",
            "error",
            {"reason": "stable_id_mismatch", "expected": expected_plan_id},
        ))

    blocks = payload.get("blocks", ())
    block_ids: set[str] = set()
    block_indexes: set[int] = set()
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            continue
        path = "$.blocks[{0}]".format(index)
        block_id = block.get("block_id")
        block_index = block.get("block_index")
        if block_id in block_ids:
            issues.append(_issue("INVALID_RECOGNITION_PLAN", path + ".block_id", "error", {"reason": "duplicate_id"}))
        if isinstance(block_id, str):
            block_ids.add(block_id)
        if block_index in block_indexes:
            issues.append(_issue(
                "INVALID_RECOGNITION_PLAN",
                path + ".block_index",
                "error",
                {"reason": "duplicate_index"},
            ))
        if isinstance(block_index, int):
            block_indexes.add(block_index)
        locator = block.get("source_locator") if isinstance(block.get("source_locator"), Mapping) else {}
        segment = block.get("segment") if isinstance(block.get("segment"), Mapping) else {}
        expected_group_id = _expected_physical_group_id(str(payload.get("plan_id") or ""), block)
        if block.get("physical_group_id") != expected_group_id:
            issues.append(_issue(
                "INVALID_RECOGNITION_PLAN",
                path + ".physical_group_id",
                "error",
                {"reason": "stable_id_mismatch", "expected": expected_group_id},
            ))
        expected_block_id = _expected_block_id(str(payload.get("plan_id") or ""), block, expected_group_id)
        if block.get("block_id") != expected_block_id:
            issues.append(_issue(
                "INVALID_RECOGNITION_PLAN",
                path + ".block_id",
                "error",
                {"reason": "stable_id_mismatch", "expected": expected_block_id},
            ))
        raw_span = locator.get("raw_span") if isinstance(locator.get("raw_span"), Mapping) else {}
        canonical_span = locator.get("canonical_span") if isinstance(locator.get("canonical_span"), Mapping) else {}
        physical_length = locator.get("physical_text_length_utf16")
        canonical_length = locator.get("physical_canonical_text_length_utf16")
        _check_span(
            raw_span,
            path + ".source_locator.raw_span",
            expected_coordinate="source_raw_text",
            code="INVALID_RECOGNITION_PLAN",
            issues=issues,
            max_length=physical_length if isinstance(physical_length, int) else None,
        )
        _check_span(
            canonical_span,
            path + ".source_locator.canonical_span",
            expected_coordinate="source_canonical_text",
            code="INVALID_RECOGNITION_PLAN",
            issues=issues,
            max_length=canonical_length if isinstance(canonical_length, int) else None,
        )
        for field in (
            "physical_raw_text_sha256",
            "physical_canonical_text_sha256",
            "raw_fragment_sha256",
            "canonical_fragment_sha256",
            "prefix_context_sha256",
            "suffix_context_sha256",
        ):
            _check_sha(locator.get(field), path + ".source_locator." + field, "INVALID_RECOGNITION_PLAN", issues)
        for field in ("index", "count", "count_total", "count_located", "count_confirmed"):
            if not isinstance(segment.get(field), int):
                continue
        count = segment.get("count")
        total = segment.get("count_total")
        located = segment.get("count_located")
        confirmed = segment.get("count_confirmed")
        seg_index = segment.get("index")
        if isinstance(seg_index, int) and isinstance(count, int) and count and seg_index >= count:
            issues.append(_issue("INVALID_RECOGNITION_PLAN", path + ".segment.index", "error"))
        if isinstance(count, int) and isinstance(total, int) and count > total:
            issues.append(_issue("INVALID_RECOGNITION_PLAN", path + ".segment.count", "error"))
        if isinstance(located, int) and isinstance(total, int) and located > total:
            issues.append(_issue("INVALID_RECOGNITION_PLAN", path + ".segment.count_located", "error"))
        if isinstance(confirmed, int) and isinstance(located, int) and confirmed > located:
            issues.append(_issue("INVALID_RECOGNITION_PLAN", path + ".segment.count_confirmed", "error"))
        text = block.get("text") if isinstance(block.get("text"), Mapping) else {}
        if source.get("text_included") is False and text.get("recognized_text") is not None:
            issues.append(_issue("PRIVACY_POLICY_VIOLATION", path + ".text.recognized_text", "error"))
        if source.get("raw_text_included") is False and text.get("raw_fragment_text") is not None:
            issues.append(_issue("PRIVACY_POLICY_VIOLATION", path + ".text.raw_fragment_text", "error"))

    for index, item in enumerate(payload.get("review_items", ())):
        if not isinstance(item, Mapping):
            continue
        block_id = item.get("block_id")
        if block_id and block_id not in block_ids:
            issues.append(_issue(
                "INVALID_RECOGNITION_PLAN",
                "$.review_items[{0}].block_id".format(index),
                "error",
                {"reason": "unknown_block_id"},
            ))
        if not block_id and item.get("block_index") not in block_indexes:
            issues.append(_issue(
                "INVALID_RECOGNITION_PLAN",
                "$.review_items[{0}].block_index".format(index),
                "error",
                {"reason": "unknown_block_index"},
            ))
    return tuple(issues)


def validate_host_snapshot(
    value: HostSnapshot | Mapping[str, Any],
    *,
    strict: bool = False,
) -> ValidationReport:
    payload = value.to_dict() if isinstance(value, HostSnapshot) else dict(value) if isinstance(value, Mapping) else value
    errors = list(_schema_issues(payload, HOST_SNAPSHOT_SCHEMA_VERSION, "INVALID_HOST_SNAPSHOT"))
    warnings: list[ValidationIssue] = []
    if isinstance(payload, Mapping):
        unknowns = _schema_policy_issues(payload, HOST_SNAPSHOT_SCHEMA_VERSION, "INVALID_HOST_SNAPSHOT", strict=strict)
        if strict:
            errors.extend(unknowns)
        else:
            warnings.extend(unknowns)
    if not errors and isinstance(payload, Mapping):
        errors.extend(_semantic_snapshot_issues(payload))
    return _report(errors, warnings)


def _semantic_snapshot_issues(payload: Mapping[str, Any]) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    if payload.get("integration_contract_version") != INTEGRATION_CONTRACT_VERSION:
        issues.append(_issue("UNSUPPORTED_INTEGRATION_CONTRACT", "$.integration_contract_version", "error"))
    if payload.get("text_contract_version") != HOST_TEXT_CONTRACT_VERSION:
        issues.append(_issue("UNSUPPORTED_HOST_TEXT_CONTRACT", "$.text_contract_version", "error"))
    if payload.get("offset_encoding") != OFFSET_ENCODING:
        issues.append(_issue("UNSUPPORTED_OFFSET_ENCODING", "$.offset_encoding", "error"))
    ids: set[str] = set()
    indexes: set[int] = set()
    for index, item in enumerate(payload.get("paragraphs", ())):
        if not isinstance(item, Mapping):
            continue
        paragraph_id = item.get("host_paragraph_id")
        paragraph_index = item.get("host_paragraph_index")
        if paragraph_id in ids:
            issues.append(_issue(
                "INVALID_HOST_SNAPSHOT",
                "$.paragraphs[{0}].host_paragraph_id".format(index),
                "error",
                {"reason": "duplicate_id"},
            ))
        if isinstance(paragraph_id, str):
            ids.add(paragraph_id)
        if paragraph_index in indexes:
            issues.append(_issue(
                "INVALID_HOST_SNAPSHOT",
                "$.paragraphs[{0}].host_paragraph_index".format(index),
                "error",
                {"reason": "duplicate_index"},
            ))
        if isinstance(paragraph_index, int):
            indexes.add(paragraph_index)
    return tuple(issues)


def validate_recognition_binding(
    value: RecognitionBinding | Mapping[str, Any],
    *,
    strict: bool = False,
) -> ValidationReport:
    payload = value.to_dict() if isinstance(value, RecognitionBinding) else dict(value) if isinstance(value, Mapping) else value
    errors = list(_schema_issues(payload, RECOGNITION_BINDING_SCHEMA_VERSION, "INVALID_RECOGNITION_BINDING"))
    warnings: list[ValidationIssue] = []
    if isinstance(payload, Mapping):
        unknowns = _schema_policy_issues(
            payload,
            RECOGNITION_BINDING_SCHEMA_VERSION,
            "INVALID_RECOGNITION_BINDING",
            strict=strict,
        )
        if strict:
            errors.extend(unknowns)
        else:
            warnings.extend(unknowns)
    if not errors and isinstance(payload, Mapping):
        errors.extend(_semantic_binding_issues(payload))
    return _report(errors, warnings)


def _semantic_binding_issues(payload: Mapping[str, Any]) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    contracts = payload.get("contracts") if isinstance(payload.get("contracts"), Mapping) else {}
    if payload.get("integration_contract_version") != INTEGRATION_CONTRACT_VERSION:
        issues.append(_issue("UNSUPPORTED_INTEGRATION_CONTRACT", "$.integration_contract_version", "error"))
    if contracts.get("source_locator_version") != SOURCE_LOCATOR_VERSION:
        issues.append(_issue("UNSUPPORTED_SCHEMA_VERSION", "$.contracts.source_locator_version", "error"))
    if contracts.get("host_text_contract_version") != HOST_TEXT_CONTRACT_VERSION:
        issues.append(_issue("UNSUPPORTED_HOST_TEXT_CONTRACT", "$.contracts.host_text_contract_version", "error"))
    if contracts.get("offset_encoding") != OFFSET_ENCODING:
        issues.append(_issue("UNSUPPORTED_OFFSET_ENCODING", "$.contracts.offset_encoding", "error"))
    _check_sha(payload.get("source_sha256"), "$.source_sha256", "INVALID_RECOGNITION_BINDING", issues, required=True)
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    blocks = tuple(item for item in payload.get("blocks", ()) if isinstance(item, Mapping))
    physicals = tuple(item for item in payload.get("physical_paragraphs", ()) if isinstance(item, Mapping))
    expected_binding_id = _expected_binding_id(payload)
    if payload.get("binding_id") != expected_binding_id:
        issues.append(_issue(
            "INVALID_RECOGNITION_BINDING",
            "$.binding_id",
            "error",
            {"reason": "stable_id_mismatch", "expected": expected_binding_id},
        ))
    block_ids: set[str] = set()
    physical_group_ids: set[str] = set()
    physical_by_group: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(physicals):
        path = "$.physical_paragraphs[{0}]".format(index)
        group_id = item.get("physical_group_id")
        if isinstance(group_id, str) and group_id:
            if group_id in physical_group_ids:
                issues.append(_issue(
                    "INVALID_RECOGNITION_BINDING",
                    path + ".physical_group_id",
                    "error",
                    {"reason": "duplicate_id"},
                ))
            physical_group_ids.add(group_id)
            physical_by_group[group_id] = item
        host_id = item.get("host_paragraph_id")
        if item.get("status") in {"matched_unique", "matched_review"} and not host_id:
            issues.append(_issue(
                "INVALID_RECOGNITION_BINDING",
                path + ".host_paragraph_id",
                "error",
                {"reason": "missing_host_reference"},
            ))
    counted = {
        "total_blocks": len(blocks),
        "confirmed_blocks": 0,
        "review_blocks": 0,
        "unresolved_blocks": 0,
        "complete_physical_groups": 0,
        "incomplete_physical_groups": 0,
    }
    blocks_by_group: dict[str, list[Mapping[str, Any]]] = {}
    for index, block in enumerate(blocks):
        path = "$.blocks[{0}]".format(index)
        binding = block.get("binding") if isinstance(block.get("binding"), Mapping) else {}
        target = block.get("host_target") if isinstance(block.get("host_target"), Mapping) else {}
        raw_span = target.get("raw_span") if isinstance(target.get("raw_span"), Mapping) else {}
        canonical_span = target.get("canonical_span") if isinstance(target.get("canonical_span"), Mapping) else {}
        preconditions = block.get("preconditions") if isinstance(block.get("preconditions"), Mapping) else {}
        status = binding.get("status")
        action = binding.get("recommended_action")
        block_id = block.get("block_id")
        if isinstance(block_id, str):
            if block_id in block_ids:
                issues.append(_issue(
                    "INVALID_RECOGNITION_BINDING",
                    path + ".block_id",
                    "error",
                    {"reason": "duplicate_id"},
                ))
            block_ids.add(block_id)
        group_id = block.get("physical_group_id")
        if isinstance(group_id, str) and group_id:
            blocks_by_group.setdefault(group_id, []).append(block)
            if status != "unresolved" and group_id not in physical_group_ids:
                issues.append(_issue(
                    "INVALID_RECOGNITION_BINDING",
                    path + ".physical_group_id",
                    "error",
                    {"reason": "unknown_physical_group"},
                ))
        if status in {"confirmed", "review", "unresolved"}:
            counted["{0}_blocks".format(status)] += 1
        expected_action = {
            "confirmed": "verify_host_range",
            "review": "preview_only",
            "unresolved": "skip",
        }.get(str(status))
        if action != expected_action:
            issues.append(_issue(
                "INVALID_RECOGNITION_BINDING",
                path + ".binding.recommended_action",
                "error",
                {"status": str(status), "expected": expected_action, "recommended_action": str(action)},
            ))
        if status == "confirmed":
            if not target.get("host_paragraph_id"):
                issues.append(_issue("INVALID_RECOGNITION_BINDING", path + ".host_target.host_paragraph_id", "error"))
            _check_span(
                raw_span,
                path + ".host_target.raw_span",
                expected_coordinate="host_snapshot_raw_text",
                code="INVALID_RECOGNITION_BINDING",
                issues=issues,
                allow_null=False,
            )
            _check_span(
                canonical_span,
                path + ".host_target.canonical_span",
                expected_coordinate="host_snapshot_canonical_text",
                code="INVALID_RECOGNITION_BINDING",
                issues=issues,
                allow_null=False,
            )
            for field in (
                "plan_id",
                "snapshot_id",
                "host_paragraph_id",
                "host_paragraph_raw_sha256",
                "host_paragraph_canonical_sha256",
                "raw_fragment_sha256",
                "canonical_fragment_sha256",
                "text_contract_version",
                "offset_encoding",
            ):
                if preconditions.get(field) in (None, ""):
                    issues.append(_issue(
                        "INVALID_RECOGNITION_BINDING",
                        path + ".preconditions." + field,
                        "error",
                        {"reason": "missing_precondition"},
                    ))
            for field in (
                "host_paragraph_raw_sha256",
                "host_paragraph_canonical_sha256",
                "raw_fragment_sha256",
                "canonical_fragment_sha256",
            ):
                _check_sha(
                    preconditions.get(field),
                    path + ".preconditions." + field,
                    "INVALID_RECOGNITION_BINDING",
                    issues,
                    required=True,
                )
            expected_preconditions = {
                "plan_id": payload.get("plan_id"),
                "snapshot_id": payload.get("snapshot_id"),
                "document_identity": payload.get("document_identity"),
                "document_revision": payload.get("document_revision"),
                "host_paragraph_id": target.get("host_paragraph_id"),
                "text_contract_version": contracts.get("host_text_contract_version"),
                "offset_encoding": contracts.get("offset_encoding"),
            }
            for field, expected in expected_preconditions.items():
                if preconditions.get(field) != expected:
                    issues.append(_issue(
                        "INVALID_RECOGNITION_BINDING",
                        path + ".preconditions." + field,
                        "error",
                        {"reason": "precondition_mismatch", "expected": expected},
                    ))
            physical = physical_by_group.get(str(group_id))
            if physical and target.get("host_paragraph_id") != physical.get("host_paragraph_id"):
                issues.append(_issue(
                    "INVALID_RECOGNITION_BINDING",
                    path + ".host_target.host_paragraph_id",
                    "error",
                    {"reason": "physical_group_host_mismatch"},
                ))
        elif status == "review":
            _check_span(
                raw_span,
                path + ".host_target.raw_span",
                expected_coordinate="host_snapshot_raw_text",
                code="INVALID_RECOGNITION_BINDING",
                issues=issues,
                allow_null=False,
            )
            _check_span(
                canonical_span,
                path + ".host_target.canonical_span",
                expected_coordinate="host_snapshot_canonical_text",
                code="INVALID_RECOGNITION_BINDING",
                issues=issues,
                allow_null=False,
            )
        elif status == "unresolved":
            if preconditions:
                issues.append(_issue("INVALID_RECOGNITION_BINDING", path + ".preconditions", "error"))
            executable_fields = (
                target.get("host_paragraph_id"),
                target.get("host_paragraph_index"),
                target.get("story_id"),
                target.get("story_type"),
                raw_span.get("start"),
                raw_span.get("end"),
                canonical_span.get("start"),
                canonical_span.get("end"),
            )
            if any(item is not None for item in executable_fields):
                issues.append(_issue(
                    "INVALID_RECOGNITION_BINDING",
                    path + ".host_target",
                    "error",
                    {"reason": "unresolved_executable_target"},
                ))
            _check_span(
                raw_span,
                path + ".host_target.raw_span",
                expected_coordinate="host_snapshot_raw_text",
                code="INVALID_RECOGNITION_BINDING",
                issues=issues,
            )
            _check_span(
                canonical_span,
                path + ".host_target.canonical_span",
                expected_coordinate="host_snapshot_canonical_text",
                code="INVALID_RECOGNITION_BINDING",
                issues=issues,
            )
    for group in physicals:
        group_id = group.get("physical_group_id")
        group_blocks = blocks_by_group.get(str(group_id), ())
        statuses = [
            (item.get("binding") if isinstance(item.get("binding"), Mapping) else {}).get("status")
            for item in group_blocks
        ]
        if group.get("status") in {"matched_unique", "matched_review"} and group_blocks and all(
            item in {"confirmed", "review"} for item in statuses
        ):
            counted["complete_physical_groups"] += 1
        else:
            counted["incomplete_physical_groups"] += 1
    for field, expected in counted.items():
        if summary.get(field) != expected:
            issues.append(_issue(
                "INVALID_RECOGNITION_BINDING",
                "$.summary." + field,
                "error",
                {"expected": expected},
            ))
    return tuple(issues)


def recognition_request_from_dict(value: Mapping[str, Any], *, strict: bool = False) -> RecognitionRequest:
    report = validate_recognition_request(value, strict=strict)
    _raise_if_invalid(report, InvalidRequestError)
    return _recognition_request_from_dict_unchecked(value, strict=strict)


def recognition_plan_from_dict(value: Mapping[str, Any], *, strict: bool = False) -> RecognitionPlan:
    report = validate_recognition_plan(value, strict=strict)
    _raise_if_invalid(report, InvalidRecognitionPlanError)
    return _recognition_plan_from_dict_unchecked(value, strict=strict)


def host_snapshot_from_dict(
    value: Mapping[str, Any],
    *,
    strict: bool = False,
) -> HostSnapshot:
    report = validate_host_snapshot(value, strict=strict)
    _raise_if_invalid(report, InvalidHostSnapshotError)
    return _host_snapshot_from_dict_unchecked(value, strict=True, allow_legacy=False)


def recognition_binding_from_dict(value: Mapping[str, Any], *, strict: bool = False) -> RecognitionBinding:
    report = validate_recognition_binding(value, strict=strict)
    _raise_if_invalid(report, InvalidRecognitionBindingError)
    return _recognition_binding_from_dict_unchecked(value, strict=strict)
