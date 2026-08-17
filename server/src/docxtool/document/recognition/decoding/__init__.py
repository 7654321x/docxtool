"""Recognition beam-decoding implementation package."""

from .candidate_selection import (
    _candidates,
    _extra_candidates,
    _legacy_type,
    _limit_candidates,
    _mode_as_legacy,
    _provider_enabled,
)
from .model import _Beam, _Context
from .pipeline import apply_recognition
from .review import _clamp, _review_assessment, _review_evidence
from .transitions import _hard_veto, _transition

_COMPATIBILITY_HELPERS = (
    _candidates,
    _extra_candidates,
    _legacy_type,
    _limit_candidates,
    _mode_as_legacy,
    _provider_enabled,
    _Beam,
    _Context,
    _clamp,
    _review_assessment,
    _review_evidence,
    _hard_veto,
    _transition,
)

__all__ = ["apply_recognition"]
