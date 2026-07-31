"""Stable, local-only recognition SDK for third-party integrations."""

from .binding import bind_recognition_plan
from .models import (
    BoundRecognitionBlock,
    HostParagraph,
    HostSnapshot,
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
    "BoundRecognitionBlock",
    "bind_recognition_plan",
    "recognize_docx",
]
