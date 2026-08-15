"""Shared helpers and imports for split WPS application tests."""

from __future__ import annotations

# This module intentionally re-exports the original WPS test fixture surface
# to keep the mechanical test split behavior-preserving.
# ruff: noqa: F401

import errno

import http.client

import json

from logging.handlers import RotatingFileHandler

from pathlib import Path

import re

import threading

from types import SimpleNamespace

from xml.etree import ElementTree

import pytest

from docx import Document

from docx.oxml import OxmlElement

from docx.oxml.ns import qn

import apps.wps.main as wps_main

from apps.wps.control import logging_adapter

from apps.wps.control import server as server_module

from apps.wps.control import document_transaction as transaction_module

from apps.wps.control import format_current_document as format_module

from apps.wps.control import recognize_document as recognition_module

from apps.wps.control.format_current_document import FormatResult

from apps.wps.control.logging_adapter import (
    document_log_context,
    file_identity,
    sanitize_wps_log_fields,
)

from apps.wps.control.recognize_document import bind_preview

from apps.wps.control.server import _safe_warnings

from docxtool.sdk import recognize_docx

from docxtool.wps_server.format_config import load_active_format_profile

def _fake_result(output_path: Path, log_dir: Path) -> FormatResult:
    log_path = log_dir / "test.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    return FormatResult(
        output_path=output_path,
        log_path=log_path,
        document_mode="NORMAL",
        paragraph_count=3,
        heading_count=1,
        body_count=2,
        export_stats={},
    )

def _add_native_heading2_numbering(document: Document, text: str) -> None:
    numbering = document.part.numbering_part.element
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), "91")
    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    number_format = OxmlElement("w:numFmt")
    number_format.set(qn("w:val"), "chineseCounting")
    level_text = OxmlElement("w:lvlText")
    level_text.set(qn("w:val"), "（%1）")
    level.extend((start, number_format, level_text))
    abstract.append(level)
    numbering.find(qn("w:num")).addprevious(abstract)

    number = OxmlElement("w:num")
    number.set(qn("w:numId"), "91")
    abstract_ref = OxmlElement("w:abstractNumId")
    abstract_ref.set(qn("w:val"), "91")
    number.append(abstract_ref)
    numbering.append(number)

    paragraph = document.add_paragraph(text)
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num_id = OxmlElement("w:numId")
    num_id.set(qn("w:val"), "91")
    num_pr.extend((ilvl, num_id))
    paragraph._p.get_or_add_pPr().append(num_pr)

def _install_fake_formatter(monkeypatch):
    def fake_format(
        source_path,
        output_path,
        *,
        operation_id,
        log_dir,
        format_config=None,
        request_id="",
    ):
        target = Path(output_path)
        target.write_bytes(b"formatted")
        return _fake_result(target, Path(log_dir))

    monkeypatch.setattr(transaction_module, "format_current_document", fake_format)

def _transaction_journal_payload(source: Path) -> dict:
    operation_id = "a" * 32
    return {
        "version": 2,
        "operation_id": operation_id,
        "state": "prepared",
        "source_path": str(source),
        "temporary_path": str(
            source.with_name(f".{source.stem}.docxtool-{operation_id[:12]}.docx")
        ),
        "backup_path": str(
            source.with_name(f".{source.stem}.docxtool-backup-{operation_id[:12]}.docx")
        ),
        "original_source_sha256": "0" * 64,
        "temporary_sha256": "1" * 64,
        "backup_sha256": None,
        "formatted_source_sha256": None,
    }

def _snapshot(raw_text: str, *, snapshot_id: str = "snap-wps") -> dict:
    return {
        "schema_version": "host-snapshot-v1",
        "integration_contract_version": "integration-contract-v1",
        "snapshot_id": snapshot_id,
        "document_identity": "doc-wps",
        "document_revision": "rev-wps",
        "host": {"kind": "wps", "platform": "windows"},
        "host_type": "wps",
        "text_contract_version": "host-text-v1",
        "offset_encoding": "utf16_code_unit",
        "paragraphs": [
            {
                "host_paragraph_id": "main:000000",
                "host_paragraph_index": 0,
                "story_id": "main",
                "story_type": "main",
                "story_paragraph_index": 0,
                "section_index": None,
                "is_in_table": False,
                "raw_text": raw_text,
            }
        ],
    }

def _multi_paragraph_snapshot(texts: list[str]) -> dict:
    snapshot = _snapshot(texts[0])
    snapshot["paragraphs"] = [
        {
            "host_paragraph_id": f"main:{index:06d}",
            "host_paragraph_index": index,
            "story_id": "main",
            "story_type": "main",
            "story_paragraph_index": index,
            "section_index": None,
            "is_in_table": False,
            "raw_text": text,
        }
        for index, text in enumerate(texts)
    ]
    return snapshot

def _control_post(server, path, *, body=b"{}", token="test-token", headers=None):
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=5
    )
    request_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-DocxTool-Request-Id": "boundary-request",
    }
    request_headers.update(headers or {})
    try:
        connection.request("POST", path, body=body, headers=request_headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        return response.status, payload
    finally:
        connection.close()

__all__ = [name for name in globals() if not name.startswith("__")]
