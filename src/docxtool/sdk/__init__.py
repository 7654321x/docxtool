"""Stable, local-only recognition SDK for third-party integrations."""

from .binding import bind_recognition_plan
from docxtool.document.source_tape import (
    HOST_TEXT_CONTRACT_VERSION,
    SOURCE_LOCATOR_VERSION,
    CanonicalTextResult,
    canonicalize_host_paragraph_text,
)
from .models import (
    BoundRecognitionBlock,
    HostParagraph,
    HostSnapshot,
    PhysicalParagraphBinding,
    RecognitionBinding,
    RecognitionBlock,
    RecognitionPlan,
    ReviewItem,
)
from .recognition import (
    RecognitionInputError,
    RecognitionSdkError,
    recognize_docx,
)

__all__ = [
    "RecognitionBlock",
    "RecognitionBinding",
    "RecognitionInputError",
    "RecognitionPlan",
    "RecognitionSdkError",
    "ReviewItem",
    "HostParagraph",
    "HostSnapshot",
    "PhysicalParagraphBinding",
    "BoundRecognitionBlock",
    "CanonicalTextResult",
    "HOST_TEXT_CONTRACT_VERSION",
    "SOURCE_LOCATOR_VERSION",
    "bind_recognition_plan",
    "canonicalize_host_paragraph_text",
    "recognize_docx",
]
