"""Central recognition tuning constants."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RecognitionConfig:
    beam_width: int = 12
    max_candidates_per_paragraph: int = 8
    hard_structure_min: float = 0.95
    core_override_threshold: float = 0.85
    key_value_score: float = 0.92
    numbering_score: float = 0.68
    semantic_title_score: float = 0.82
    legacy_score: float = 0.55
    external_style_score: float = 0.18
    docxtool_style_score: float = 0.08
    enable_diagnostics: bool = True
    text_preview_length: int = 12
    unknown_render_type: str = "warn_body"
    review_low_score: float = 0.6
    review_margin: float = 0.08

    def __post_init__(self) -> None:
        if self.beam_width < 2:
            raise ValueError("beam_width must be at least 2")
        if self.max_candidates_per_paragraph < 2:
            raise ValueError("max_candidates_per_paragraph must be at least 2")
        for name in ("hard_structure_min", "core_override_threshold", "key_value_score", "numbering_score", "semantic_title_score", "legacy_score", "external_style_score", "docxtool_style_score", "review_low_score", "review_margin"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.text_preview_length < 0:
            raise ValueError("text_preview_length cannot be negative")
        if self.unknown_render_type not in {"warn_body", "strict"}:
            raise ValueError("unknown_render_type must be 'warn_body' or 'strict'")


DEFAULT_CONFIG = RecognitionConfig()
