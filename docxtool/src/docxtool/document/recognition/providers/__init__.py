"""Built-in recognition candidate providers in stable registration order."""

from .base import Candidate, CandidateContext, CandidateProvider
from .body_structure import GlossaryCandidateProvider, Title2CandidateProvider
from .inline_heading import InlineHeadingCandidateProvider
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
    Title2CandidateProvider(),
    GlossaryCandidateProvider(),
    InlineHeadingCandidateProvider(),
    CoreCandidateProvider(),
    LegacyCandidateProvider(),
    StyleCandidateProvider(),
)

__all__ = [
    "Candidate",
    "CandidateContext",
    "CandidateProvider",
    "GlossaryCandidateProvider",
    "InlineHeadingCandidateProvider",
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
    "Title2CandidateProvider",
]
