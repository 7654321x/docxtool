"""Stable public SDK contract constants."""

from __future__ import annotations

INTEGRATION_CONTRACT_VERSION = "integration-contract-v1"
SDK_MANIFEST_SCHEMA_VERSION = "sdk-manifest-v1"
RECOGNITION_REQUEST_SCHEMA_VERSION = "recognition-request-v1"
RECOGNITION_PLAN_SCHEMA_VERSION = "recognition-plan-v1"
HOST_SNAPSHOT_SCHEMA_VERSION = "host-snapshot-v1"
RECOGNITION_BINDING_SCHEMA_VERSION = "recognition-binding-v1"
SDK_ERROR_SCHEMA_VERSION = "sdk-error-v1"

SOURCE_LOCATOR_VERSION = "source-locator-v2"
HOST_TEXT_CONTRACT_VERSION = "host-text-v1"
OFFSET_ENCODING = "utf16_code_unit"

PROCESSING_MODES = ("strict", "structural", "normalize")
RECOGNITION_MODES = ("legacy", "shadow", "authoritative")
STORY_TYPES = (
    "main",
    "header",
    "footer",
    "footnote",
    "endnote",
    "comment",
    "text_frame",
    "unknown",
)
BINDING_STATUSES = ("confirmed", "review", "unresolved")
RECOMMENDED_ACTIONS = ("verify_host_range", "preview_only", "skip")

CAPABILITIES = (
    "multi_segment_paragraph",
    "source_raw_locator",
    "source_canonical_locator",
    "host_snapshot_binding",
    "local_ambiguity",
    "segment_format_features",
    "east_asia_font_features",
    "text_optional_output",
    "json_schema_validation",
)

ERROR_CODES = (
    "INVALID_RECOGNITION_REQUEST",
    "INVALID_RECOGNITION_PLAN",
    "INVALID_HOST_SNAPSHOT",
    "INVALID_RECOGNITION_BINDING",
    "UNSUPPORTED_INTEGRATION_CONTRACT",
    "UNSUPPORTED_SCHEMA_VERSION",
    "UNSUPPORTED_HOST_TEXT_CONTRACT",
    "UNSUPPORTED_OFFSET_ENCODING",
    "SOURCE_DOCUMENT_CHANGED",
    "SOURCE_LOCATOR_NOT_CONFIRMED",
    "PHYSICAL_PARAGRAPH_UNMATCHED",
    "SOURCE_OCCURRENCE_AMBIGUOUS",
    "SOURCE_TEXT_HASH_MISMATCH",
    "SEGMENT_GROUP_INCOMPLETE",
    "INVALID_DOCX_INPUT",
    "RECOGNITION_FAILED",
    "BINDING_FAILED",
    "PRIVACY_POLICY_VIOLATION",
)

SCHEMA_FILENAMES = {
    SDK_MANIFEST_SCHEMA_VERSION: "sdk-manifest-v1.schema.json",
    RECOGNITION_REQUEST_SCHEMA_VERSION: "recognition-request-v1.schema.json",
    RECOGNITION_PLAN_SCHEMA_VERSION: "recognition-plan-v1.schema.json",
    HOST_SNAPSHOT_SCHEMA_VERSION: "host-snapshot-v1.schema.json",
    RECOGNITION_BINDING_SCHEMA_VERSION: "recognition-binding-v1.schema.json",
    SDK_ERROR_SCHEMA_VERSION: "sdk-error-v1.schema.json",
}
