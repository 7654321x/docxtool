"""SDK manifest and capability negotiation."""

from __future__ import annotations

from docxtool.version import package_version

from .constants import (
    CAPABILITIES,
    HOST_SNAPSHOT_SCHEMA_VERSION,
    HOST_SNAPSHOT_SUMMARY_SCHEMA_VERSION,
    HOST_TEXT_CONTRACT_VERSION,
    INTEGRATION_CONTRACT_VERSION,
    OFFSET_ENCODING,
    RECOGNITION_BINDING_SCHEMA_VERSION,
    RECOGNITION_PLAN_SCHEMA_VERSION,
    SDK_MANIFEST_SCHEMA_VERSION,
    SOURCE_LOCATOR_VERSION,
    VALIDATION_REPORT_SCHEMA_VERSION,
)
from .models import SdkManifest


def get_sdk_manifest() -> SdkManifest:
    """Return a text-free manifest for host capability negotiation.

    宿主适配器只通过 manifest 决定是否能继续识别和绑定；这里必须使用
    真实包版本，不能使用构建日期或 Web 服务版本，否则 WPS、Office.js、
    VSTO 等宿主会把同一个 wheel 识别成不同能力集。
    """
    return SdkManifest(
        schema_version=SDK_MANIFEST_SCHEMA_VERSION,
        package_version=package_version(),
        integration_contract_versions=(INTEGRATION_CONTRACT_VERSION,),
        recognition_plan_versions=(RECOGNITION_PLAN_SCHEMA_VERSION,),
        host_snapshot_versions=(HOST_SNAPSHOT_SCHEMA_VERSION,),
        recognition_binding_versions=(RECOGNITION_BINDING_SCHEMA_VERSION,),
        validation_report_versions=(VALIDATION_REPORT_SCHEMA_VERSION,),
        host_snapshot_summary_versions=(HOST_SNAPSHOT_SUMMARY_SCHEMA_VERSION,),
        source_locator_versions=(SOURCE_LOCATOR_VERSION,),
        host_text_contract_versions=(HOST_TEXT_CONTRACT_VERSION,),
        offset_encodings=(OFFSET_ENCODING,),
        capabilities=CAPABILITIES,
        binding_scope={
            "supported_story_types": ["main"],
            "excluded_story_types": ["header", "footer", "footnote", "endnote", "comment", "text_frame"],
            "tables": "excluded",
            "requires_raw_text": True,
            "range_execution": "host_must_verify",
        },
    )
