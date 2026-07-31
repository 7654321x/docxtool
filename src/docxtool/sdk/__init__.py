"""Stable, local-only recognition SDK for third-party integrations."""

from .binding import bind_recognition_plan
from .errors import (
    BindingError,
    DocxToolSdkError,
    InvalidHostSnapshotError,
    InvalidRecognitionBindingError,
    InvalidRecognitionPlanError,
    InvalidRequestError,
    PrivacyPolicyError,
    UnsupportedContractError,
)
from .manifest import get_sdk_manifest
from docxtool.document.source_tape import (
    HOST_TEXT_CONTRACT_VERSION,
    SOURCE_LOCATOR_VERSION,
    CanonicalTextResult,
    canonicalize_host_paragraph_text,
)
from .models import (
    BoundRecognitionBlock,
    HostParagraph,
    HostSnapshot,
    PhysicalParagraphBinding,
    RecognitionBinding,
    RecognitionBlock,
    RecognitionPlan,
    RecognitionRequest,
    ReviewItem,
    SdkManifest,
    host_snapshot_from_dict,
    recognition_binding_from_dict,
    recognition_plan_from_dict,
)
from .recognition import (
    RecognitionInputError,
    RecognitionSdkError,
    recognize_docx,
)
from .validation import (
    load_json_schema,
    validate_host_snapshot,
    validate_recognition_binding,
    validate_recognition_plan,
    validate_recognition_request,
    validate_sdk_error,
    validate_sdk_manifest,
)

__all__ = [
    "BindingError",
    "DocxToolSdkError",
    "InvalidHostSnapshotError",
    "InvalidRecognitionBindingError",
    "InvalidRecognitionPlanError",
    "InvalidRequestError",
    "PrivacyPolicyError",
    "UnsupportedContractError",
    "RecognitionBlock",
    "RecognitionBinding",
    "RecognitionInputError",
    "RecognitionPlan",
    "RecognitionRequest",
    "RecognitionSdkError",
    "ReviewItem",
    "SdkManifest",
    "HostParagraph",
    "HostSnapshot",
    "PhysicalParagraphBinding",
    "BoundRecognitionBlock",
    "CanonicalTextResult",
    "HOST_TEXT_CONTRACT_VERSION",
    "SOURCE_LOCATOR_VERSION",
    "bind_recognition_plan",
    "canonicalize_host_paragraph_text",
    "get_sdk_manifest",
    "host_snapshot_from_dict",
    "load_json_schema",
    "recognition_binding_from_dict",
    "recognition_plan_from_dict",
    "recognize_docx",
    "validate_host_snapshot",
    "validate_recognition_binding",
    "validate_recognition_plan",
    "validate_recognition_request",
    "validate_sdk_error",
    "validate_sdk_manifest",
]
