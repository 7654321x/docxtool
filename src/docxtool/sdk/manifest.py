"""SDK manifest and capability negotiation."""

from __future__ import annotations

from docxtool import __version__ as PACKAGE_VERSION

from .constants import (
    CAPABILITIES,
    HOST_SNAPSHOT_SCHEMA_VERSION,
    HOST_TEXT_CONTRACT_VERSION,
    INTEGRATION_CONTRACT_VERSION,
    OFFSET_ENCODING,
    RECOGNITION_BINDING_SCHEMA_VERSION,
    RECOGNITION_PLAN_SCHEMA_VERSION,
    SDK_MANIFEST_SCHEMA_VERSION,
    SOURCE_LOCATOR_VERSION,
)
from .models import SdkManifest


def get_sdk_manifest() -> SdkManifest:
    """Return a text-free manifest for host capability negotiation."""
    return SdkManifest(
        schema_version=SDK_MANIFEST_SCHEMA_VERSION,
        package_version=PACKAGE_VERSION,
        integration_contract_versions=(INTEGRATION_CONTRACT_VERSION,),
        recognition_plan_versions=(RECOGNITION_PLAN_SCHEMA_VERSION,),
        host_snapshot_versions=(HOST_SNAPSHOT_SCHEMA_VERSION,),
        recognition_binding_versions=(RECOGNITION_BINDING_SCHEMA_VERSION,),
        source_locator_versions=(SOURCE_LOCATOR_VERSION,),
        host_text_contract_versions=(HOST_TEXT_CONTRACT_VERSION,),
        offset_encodings=(OFFSET_ENCODING,),
        capabilities=CAPABILITIES,
    )
