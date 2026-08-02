"""Compatibility facade for the recognition beam decoder."""

from __future__ import annotations

from typing import Any

from .candidates import Candidate, CandidateContext, DEFAULT_PROVIDERS
from .config import RecognitionConfig
from .decoding.candidate_selection import (
    _EMBEDDED_TITLE_RE,
    _MEETING_LABELS,
    _SOURCE_NOTE_RE,
    _candidates,
    _extra_candidates,
    _legacy_type,
    _limit_candidates,
    _mode_as_legacy,
    _provider_enabled,
)
from .decoding.model import _Beam, _Context
from .decoding.pipeline import apply_recognition as _apply_recognition
from .decoding.review import (
    _HEADING_CONFLICT_EVIDENCE,
    _HEADING_TYPES,
    _STRUCTURE_SENSITIVE_TYPES,
    _clamp,
    _review_assessment,
    _review_evidence,
)
from .decoding.transitions import _hard_veto, _transition


def apply_recognition(data: Any, config: RecognitionConfig | None = None) -> None:
    """Preserve the legacy provider patch point while delegating decoding."""
    _apply_recognition(data, config, providers=DEFAULT_PROVIDERS)


_COMPATIBILITY_HELPERS = (
    Candidate,
    CandidateContext,
    _EMBEDDED_TITLE_RE,
    _MEETING_LABELS,
    _SOURCE_NOTE_RE,
    _Beam,
    _Context,
    _candidates,
    _extra_candidates,
    _legacy_type,
    _limit_candidates,
    _mode_as_legacy,
    _provider_enabled,
    _HEADING_CONFLICT_EVIDENCE,
    _HEADING_TYPES,
    _STRUCTURE_SENSITIVE_TYPES,
    _clamp,
    _review_assessment,
    _review_evidence,
    _hard_veto,
    _transition,
)

__all__ = ["apply_recognition"]
