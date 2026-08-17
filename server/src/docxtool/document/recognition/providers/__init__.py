"""Built-in recognition candidate providers in stable registration order."""

from .base import Candidate, CandidateContext, CandidateProvider
from .compatibility import CoreCandidateProvider, LegacyCandidateProvider, StyleCandidateProvider
from .key_value import KeyValueCandidateProvider
from .numbering import NumberingCandidateProvider
from .semantic import FrontMatterMetadataCandidateProvider, SemanticCandidateProvider, SourceListNumberingCandidateProvider
from .structural import StructuralCandidateProvider


DEFAULT_PROVIDERS = (
    StructuralCandidateProvider(),
    KeyValueCandidateProvider(),
    NumberingCandidateProvider(),
    SemanticCandidateProvider(),
    FrontMatterMetadataCandidateProvider(),
    SourceListNumberingCandidateProvider(),
    CoreCandidateProvider(),
    LegacyCandidateProvider(),
    StyleCandidateProvider(),
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
