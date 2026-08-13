"""Apply one managed letterhead without invoking document recognition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict

from docx import Document
from docx.text.paragraph import Paragraph

from docxtool.document.analysis.letterhead import extract_letterhead_fields
from docxtool.document.engine.letterhead import apply_letterhead, detect_letterhead
from docxtool.document.engine.typography import apply_digit_latin_font
from docxtool.document.style_config import PageSettings, StyleRule
from docxtool.security import validate_docx_integrity

from .logging_adapter import document_log_context, log_event


_DOCUMENT_NUMBER_RE = re.compile(
    r"^(?P<agency_code>[^\s，。；：:（）()《》“”〔〕]{1,40})"
    r"〔(?P<year>\d{4})〕(?P<sequence>\d{1,6})号$"
)


class LetterheadCommandError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LetterheadOperationResult:
    output_path: Path
    log_path: Path
    action: str
    previous_status: str


def _required_text(value: object, code: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise LetterheadCommandError(code)
    text = value.strip()
    if not text or len(text) > maximum or any(character in text for character in "\r\n"):
        raise LetterheadCommandError(code)
    return text


def normalize_letterhead_request(value: object) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise LetterheadCommandError("WPS_LETTERHEAD_FORM_INVALID")
    mark_text = _required_text(
        value.get("mark_text"), "WPS_LETTERHEAD_MARK_REQUIRED", 80
    )
    document_number = _required_text(
        value.get("document_number"),
        "WPS_LETTERHEAD_DOCUMENT_NUMBER_INVALID",
        80,
    )
    number_match = _DOCUMENT_NUMBER_RE.fullmatch(document_number)
    if number_match is None:
        raise LetterheadCommandError("WPS_LETTERHEAD_DOCUMENT_NUMBER_INVALID")
    signer = value.get("signer", "")
    if not isinstance(signer, str):
        raise LetterheadCommandError("WPS_LETTERHEAD_SIGNER_INVALID")
    signer = signer.strip()
    if len(signer) > 30 or any(character in signer for character in "\r\n"):
        raise LetterheadCommandError("WPS_LETTERHEAD_SIGNER_INVALID")
    separator_style = value.get("separator_style", "straight")
    if separator_style not in {"straight", "star"}:
        raise LetterheadCommandError("WPS_LETTERHEAD_SEPARATOR_INVALID")
    replace_existing = value.get("replace_existing", False)
    if not isinstance(replace_existing, bool):
        raise LetterheadCommandError("WPS_LETTERHEAD_REPLACE_INVALID")
    return {
        "mark_text": mark_text,
        "document_number": document_number,
        "agency_code": number_match.group("agency_code"),
        "year": int(number_match.group("year")),
        "sequence": int(number_match.group("sequence")),
        "signer": signer,
        "separator_style": separator_style,
        "replace_existing": replace_existing,
    }


def _page_settings(document) -> PageSettings:
    section = document.sections[0]
    page_width_cm = section.page_width.cm
    page_height_cm = section.page_height.cm
    margin_top_cm = section.top_margin.cm
    margin_bottom_cm = section.bottom_margin.cm
    margin_left_cm = section.left_margin.cm
    margin_right_cm = section.right_margin.cm
    line_spacing_pt = None
    body_style = next(
        (style for style in document.styles if style.style_id == "DCT-Body"),
        None,
    )
    if body_style is not None:
        spacing = body_style.paragraph_format.line_spacing
        if hasattr(spacing, "pt") and spacing.pt > 0:
            line_spacing_pt = float(spacing.pt)
    if line_spacing_pt is None:
        spacing = document.styles["Normal"].paragraph_format.line_spacing
        if hasattr(spacing, "pt") and spacing.pt > 0:
            line_spacing_pt = float(spacing.pt)
    if line_spacing_pt is None:
        line_spacing_pt = 28.0
    return PageSettings(
        page_width_cm=page_width_cm,
        page_height_cm=page_height_cm,
        margin_top_cm=margin_top_cm,
        margin_bottom_cm=margin_bottom_cm,
        margin_left_cm=margin_left_cm,
        margin_right_cm=margin_right_cm,
        line_spacing_value=line_spacing_pt,
    )


def inspect_letterhead(source_path: str) -> Dict[str, Any]:
    source = Path(source_path).expanduser().resolve()
    if source.suffix.lower() != ".docx" or not source.is_file():
        raise LetterheadCommandError("INVALID_DOCX_INPUT")
    document = Document(source)
    detection = detect_letterhead(document)
    fields = extract_letterhead_fields(document, detection)
    if fields is not None and fields.issuance_mode != "single":
        raise LetterheadCommandError("WPS_LETTERHEAD_JOINT_SOURCE_UNSUPPORTED")
    return {
        "status": detection.status,
        "exists": detection.status != "none",
        "replaceable": detection.status in {"managed", "recognized_external"},
        "fields": (
            {
                "mark_text": fields.mark_text,
                "document_number": (
                    f"{fields.agency_code}〔{fields.year}〕{fields.sequence}号"
                ),
                "signer": "、".join(fields.signers),
                "separator_style": fields.separator_style,
            }
            if fields is not None
            else None
        ),
    }


def add_letterhead_to_document(
    source_path: str,
    output_path: str,
    letterhead_request: object,
    *,
    operation_id: str,
    log_dir: Path,
    request_id: str = "",
) -> LetterheadOperationResult:
    source = Path(source_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()
    if source.suffix.lower() != ".docx" or not source.is_file():
        raise LetterheadCommandError("INVALID_DOCX_INPUT")
    if target.suffix.lower() != ".docx" or source == target:
        raise LetterheadCommandError("INVALID_DOCX_OUTPUT")
    payload = normalize_letterhead_request(letterhead_request)
    with document_log_context(source, log_dir, operation_id, request_id) as log_path:
        document = Document(source)
        detection = detect_letterhead(document)
        existing_fields = extract_letterhead_fields(document, detection)
        if (
            existing_fields is not None
            and existing_fields.issuance_mode != "single"
        ):
            raise LetterheadCommandError(
                "WPS_LETTERHEAD_JOINT_SOURCE_UNSUPPORTED"
            )
        if detection.status != "none" and not payload["replace_existing"]:
            raise LetterheadCommandError("WPS_LETTERHEAD_ALREADY_EXISTS")
        if detection.status == "unknown":
            raise LetterheadCommandError("WPS_LETTERHEAD_EXISTING_AMBIGUOUS")
        config = {
            "schema_version": 1,
            "enabled": True,
            "document_direction": "upward" if payload["signer"] else "downward",
            "issuance_mode": "single",
            "mark_display_mode": "agency_only",
            "joint_mark_scope": "all_agencies",
            "agencies": [{
                "id": "agency-1",
                "name": payload["mark_text"],
                "short_name": "",
                "role": "sponsor",
                "order": 1,
            }],
            "document_number": {
                "agency_code": payload["agency_code"],
                "year": payload["year"],
                "sequence": payload["sequence"],
            },
            "signers": ([{
                "id": "signer-1",
                "agency_id": "agency-1",
                "name": payload["signer"],
                "label": "签发人",
                "order": 1,
            }] if payload["signer"] else []),
            "separator_style": payload["separator_style"],
            "existing_policy": "preserve_external",
            "replace_managed": True,
            "layout_version": 1,
        }
        try:
            result = apply_letterhead(
                document,
                config,
                detection=detection,
                rules=[StyleRule.default_for_row(index) for index in range(24)],
                settings=_page_settings(document),
            )
        except ValueError as exc:
            if str(exc) == "LETTERHEAD_MARK_TOO_LONG":
                raise LetterheadCommandError(
                    "WPS_LETTERHEAD_MARK_TOO_LONG"
                ) from exc
            if str(exc) == "LETTERHEAD_JOINT_SOURCE_UNSUPPORTED":
                raise LetterheadCommandError(
                    "WPS_LETTERHEAD_JOINT_SOURCE_UNSUPPORTED"
                ) from exc
            raise
        for element in result.protected_elements:
            apply_digit_latin_font(Paragraph(element, document._body))
        document.save(target)
        validate_docx_integrity(target)
        log_event(
            "INFO",
            "letterhead",
            "letterhead.add.completed",
            "当前文档版头已生成",
            {
                "request_id": request_id,
                "operation_id_short": operation_id[:12],
                "replaced": detection.status != "none",
                "separator_style": payload["separator_style"],
                "signer_present": bool(payload["signer"]),
                "mark_length": len(payload["mark_text"]),
                "document_number_length": len(payload["document_number"]),
            },
        )
        return LetterheadOperationResult(
            output_path=target,
            log_path=Path(log_path),
            action=result.action,
            previous_status=detection.status,
        )


__all__ = [
    "LetterheadCommandError",
    "LetterheadOperationResult",
    "add_letterhead_to_document",
    "inspect_letterhead",
    "normalize_letterhead_request",
]
