from __future__ import annotations

from docxtool.document.recognition import candidates
from docxtool.document.recognition import context
from docxtool.document.recognition import decoder
from docxtool.document.recognition import decoding
from docxtool.document.recognition import global_context
from docxtool.document.recognition import providers


def test_candidate_facade_reexports_provider_types() -> None:
    assert candidates.Candidate is providers.Candidate
    assert candidates.CandidateContext is providers.CandidateContext
    assert candidates.CandidateProvider is providers.CandidateProvider
    assert candidates.StructuralCandidateProvider is providers.StructuralCandidateProvider
    assert candidates.StyleCandidateProvider is providers.StyleCandidateProvider


def test_candidate_provider_registration_order_is_stable() -> None:
    assert candidates.DEFAULT_PROVIDERS is providers.DEFAULT_PROVIDERS
    assert tuple(provider.name for provider in candidates.DEFAULT_PROVIDERS) == (
        "structural",
        "key-value",
        "numbering",
        "semantic",
        "front-metadata",
        "source-list-numbering",
        "core",
        "legacy",
        "style",
    )


def test_global_context_facade_reexports_context_api() -> None:
    assert global_context.DocumentContext is context.DocumentContext
    assert global_context.HeadingFamily is context.HeadingFamily
    assert global_context.analyze_document_context is context.analyze_document_context


def test_decoder_facade_reexports_internal_models() -> None:
    assert decoder._Context is decoding._Context
    assert decoder._Beam is decoding._Beam
