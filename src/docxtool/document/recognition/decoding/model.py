"""Internal beam-search data models."""

from __future__ import annotations

from dataclasses import dataclass

from ..candidates import Candidate, CandidateContext
from ..features import ParagraphFeatures
from ..global_context import DocumentContext
from ..model import DocumentMode, ParagraphType, SectionKind


@dataclass(frozen=True)
class _Context(CandidateContext):
    mode: DocumentMode
    previous_type: ParagraphType | None
    index: int
    previous_types: tuple[ParagraphType, ...] = ()
    following_features: tuple[ParagraphFeatures, ...] = ()
    boundary_before: bool = False
    document_context: DocumentContext | None = None


@dataclass(frozen=True)
class _Beam:
    score: float
    types: tuple[ParagraphType, ...]
    reasons: tuple[str, ...]
    sections: tuple[SectionKind, ...]
    candidate_options: tuple[tuple[Candidate, ...], ...] = ()
    selected_candidates: tuple[Candidate, ...] = ()
