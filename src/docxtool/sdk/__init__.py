"""Stable, local-only recognition SDK for third-party integrations."""

from .models import RecognitionBlock, RecognitionPlan, ReviewItem
from .recognition import (
    RecognitionInputError,
    RecognitionSdkError,
    recognize_docx,
)

__all__ = [
    "RecognitionBlock",
    "RecognitionInputError",
    "RecognitionPlan",
    "RecognitionSdkError",
    "ReviewItem",
    "recognize_docx",
]
