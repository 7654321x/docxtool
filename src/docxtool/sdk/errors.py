"""Stable SDK exceptions and JSON error payloads."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .constants import SDK_ERROR_SCHEMA_VERSION

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


def _redacted_details(details: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not details:
        return {}
    safe = {}
    for key, value in details.items():
        if key not in _DETAIL_ALLOWLIST:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
        elif isinstance(value, (list, tuple)):
            safe[str(key)] = [
                item for item in value if isinstance(item, (str, int, float, bool)) or item is None
            ]
        elif isinstance(value, Mapping):
            safe[str(key)] = _redacted_details(value)
        else:
            safe[str(key)] = str(type(value).__name__)
    return safe


class DocxToolSdkError(RuntimeError):
    """Base public SDK error with a stable JSON representation."""

    code = "RECOGNITION_FAILED"
    retryable = False

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        code: Optional[str] = None,
        retryable: Optional[bool] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        self.code = code or self.code
        self.retryable = self.retryable if retryable is None else bool(retryable)
        self.details = _redacted_details(details)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SDK_ERROR_SCHEMA_VERSION,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }


class InvalidRequestError(DocxToolSdkError):
    code = "INVALID_RECOGNITION_REQUEST"


class InvalidRecognitionPlanError(DocxToolSdkError):
    code = "INVALID_RECOGNITION_PLAN"


class InvalidHostSnapshotError(DocxToolSdkError):
    code = "INVALID_HOST_SNAPSHOT"


class InvalidRecognitionBindingError(DocxToolSdkError):
    code = "INVALID_RECOGNITION_BINDING"


class UnsupportedContractError(DocxToolSdkError):
    code = "UNSUPPORTED_INTEGRATION_CONTRACT"


class BindingError(DocxToolSdkError):
    code = "BINDING_FAILED"


class PrivacyPolicyError(DocxToolSdkError):
    code = "PRIVACY_POLICY_VIOLATION"


class RecognitionSdkError(DocxToolSdkError):
    code = "RECOGNITION_FAILED"


class RecognitionInputError(InvalidRequestError):
    code = "INVALID_DOCX_INPUT"
