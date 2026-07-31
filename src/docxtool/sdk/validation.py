"""JSON Schema loading and public SDK validation helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping

try:  # Python 3.9+
    from importlib.resources import files
except ImportError:  # pragma: no cover - exercised on Python 3.8
    from importlib_resources import files

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from .constants import (
    HOST_SNAPSHOT_SCHEMA_VERSION,
    RECOGNITION_REQUEST_SCHEMA_VERSION,
    RECOGNITION_BINDING_SCHEMA_VERSION,
    RECOGNITION_PLAN_SCHEMA_VERSION,
    SCHEMA_FILENAMES,
    SDK_ERROR_SCHEMA_VERSION,
    SDK_MANIFEST_SCHEMA_VERSION,
)
from .errors import (
    DocxToolSdkError,
    InvalidHostSnapshotError,
    InvalidRecognitionBindingError,
    InvalidRecognitionPlanError,
)
from .manifest import get_sdk_manifest
from .models import (
    HostSnapshot,
    RecognitionBinding,
    RecognitionPlan,
    RecognitionRequest,
    host_snapshot_from_dict,
    recognition_binding_from_dict,
    recognition_plan_from_dict,
)


def load_json_schema(schema_version: str) -> Dict[str, Any]:
    """Load an installed public SDK JSON Schema by version."""
    filename = SCHEMA_FILENAMES.get(schema_version)
    if not filename:
        raise DocxToolSdkError(
            "未知 schema 版本",
            code="UNSUPPORTED_SCHEMA_VERSION",
            details={"path": "schema_version"},
        )
    schema_path = files("docxtool.resources.schemas").joinpath(filename)
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _schema_error(exc: JsonSchemaValidationError) -> Dict[str, str]:
    path = ".".join(str(item) for item in exc.absolute_path)
    if exc.validator == "required" and isinstance(exc.message, str) and "'" in exc.message:
        missing = exc.message.split("'", 2)[1]
        path = ".".join(item for item in (path, missing) if item)
    return {"path": path or "$", "validator": str(exc.validator)}


def _validate_schema(value: Mapping[str, Any], schema_version: str, error_cls: type[DocxToolSdkError]) -> None:
    try:
        Draft202012Validator(load_json_schema(schema_version)).validate(value)
    except JsonSchemaValidationError as exc:
        details = _schema_error(exc)
        raise error_cls(
            "JSON 协议字段不合法: {0}".format(details["path"]),
            details=details,
        ) from exc


def validate_sdk_manifest(value: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    payload = get_sdk_manifest().to_dict() if value is None else dict(value)
    _validate_schema(payload, SDK_MANIFEST_SCHEMA_VERSION, DocxToolSdkError)
    return payload


def validate_recognition_request(
    value: RecognitionRequest | Mapping[str, Any],
    *,
    strict: bool = False,
) -> RecognitionRequest:
    payload = value.to_dict() if isinstance(value, RecognitionRequest) else dict(value)
    _validate_schema(payload, RECOGNITION_REQUEST_SCHEMA_VERSION, DocxToolSdkError)
    return RecognitionRequest.from_dict(payload, strict=strict)


def validate_sdk_error(value: Mapping[str, Any]) -> Dict[str, Any]:
    payload = dict(value)
    _validate_schema(payload, SDK_ERROR_SCHEMA_VERSION, DocxToolSdkError)
    return payload


def validate_recognition_plan(
    value: RecognitionPlan | Mapping[str, Any],
    *,
    strict: bool = False,
) -> RecognitionPlan:
    payload = value.to_dict() if isinstance(value, RecognitionPlan) else dict(value)
    _validate_schema(payload, RECOGNITION_PLAN_SCHEMA_VERSION, InvalidRecognitionPlanError)
    return recognition_plan_from_dict(payload, strict=strict)


def validate_host_snapshot(
    value: HostSnapshot | Mapping[str, Any],
    *,
    strict: bool = False,
) -> HostSnapshot:
    payload = value.to_dict() if isinstance(value, HostSnapshot) else dict(value)
    _validate_schema(payload, HOST_SNAPSHOT_SCHEMA_VERSION, InvalidHostSnapshotError)
    snapshot = host_snapshot_from_dict(payload, strict=True, allow_legacy=False)
    if strict:
        return snapshot
    return snapshot


def validate_recognition_binding(
    value: RecognitionBinding | Mapping[str, Any],
    *,
    strict: bool = False,
) -> RecognitionBinding:
    payload = value.to_dict() if isinstance(value, RecognitionBinding) else dict(value)
    _validate_schema(payload, RECOGNITION_BINDING_SCHEMA_VERSION, InvalidRecognitionBindingError)
    return recognition_binding_from_dict(payload, strict=strict)
