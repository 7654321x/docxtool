"""Compatibility facade for candidate providers.

The implementation lives in :mod:`docxtool.document.recognition.providers`.
This module preserves the original import path and provider registration order.
"""

from __future__ import annotations

from .providers import (
    Candidate,
    CandidateContext,
    CandidateProvider,
    CoreCandidateProvider,
    DEFAULT_PROVIDERS,
    FrontMatterMetadataCandidateProvider,
    KeyValueCandidateProvider,
    LegacyCandidateProvider,
    NumberingCandidateProvider,
    SemanticCandidateProvider,
    SourceListNumberingCandidateProvider,
    StructuralCandidateProvider,
    StyleCandidateProvider,
)
from .providers.base import (
    _body_like_candidate,
    _context_evidence_for,
    _section_hint_for_type,
    _soften_legacy_body_in_front_context,
    _soften_unverified_structure,
)
from .providers.compatibility import _legacy_type

_COMPATIBILITY_HELPERS = (
    _body_like_candidate,
    _context_evidence_for,
    _legacy_type,
    _section_hint_for_type,
    _soften_legacy_body_in_front_context,
    _soften_unverified_structure,
)

__all__ = [
    "Candidate",
    "CandidateContext",
    "CandidateProvider",
    "CoreCandidateProvider",
    "DEFAULT_PROVIDERS",
    "FrontMatterMetadataCandidateProvider",
    "KeyValueCandidateProvider",
    "LegacyCandidateProvider",
    "NumberingCandidateProvider",
    "SemanticCandidateProvider",
    "SourceListNumberingCandidateProvider",
    "StructuralCandidateProvider",
    "StyleCandidateProvider",
]
