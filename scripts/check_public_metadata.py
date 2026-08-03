"""Reject private fixture metadata from public release manifests and reports."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, List, Mapping, Sequence


_DOCX_NAME_RE = re.compile(r"(?i)(?:^|[\\/\s`\"'])[^\r\n]*\.docx(?:$|[\s`\"',)])")
_TEST_DOCX_RE = re.compile(r"(?i)(?:^|[^A-Za-z0-9_])test_docx(?:[\\/]|$)")
_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]")
_POSIX_HOME_RE = re.compile(r"(?<![A-Za-z0-9])/(?:home|Users)/[^\s`\"']+")
_SOURCE_HASH_RE = re.compile(r"(?i)(?:source|源文档|原始)[^\r\n]{0,48}\b[0-9a-f]{64}\b")
_SENSITIVE_NAME_RE = re.compile(r"(?:会议|讲话|职务|机构|单位|姓名)")
_SOURCE_HASH_KEYS = frozenset({
    "source_sha256",
    "source_hash",
    "source_document_sha256",
    "original_source_sha256",
    "源文档sha256",
    "原文sha256",
})
_SOURCE_NAME_KEYS = frozenset({
    "source_name",
    "source_filename",
    "original_filename",
    "原始文件名",
    "文件名",
})
_FIXTURE_NAME_KEYS = frozenset({"fixture_name", "fixture_filename", "document_name", "样本名称"})


@dataclass(frozen=True)
class Finding:
    code: str
    path: str


def _append(findings: List[Finding], code: str, path: str) -> None:
    finding = Finding(code=code, path=path)
    if finding not in findings:
        findings.append(finding)


def _scan_json_value(value: Any, path: str, findings: List[Finding]) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.casefold()
            item_path = f"{path}.{key}"
            if normalized in _SOURCE_HASH_KEYS or (
                "source" in normalized and "sha" in normalized
            ):
                _append(findings, "SOURCE_SHA256", item_path)
            if normalized in _SOURCE_NAME_KEYS:
                _append(findings, "FIXTURE_NAME", item_path)
            if (
                normalized in _FIXTURE_NAME_KEYS
                and isinstance(item, str)
                and _SENSITIVE_NAME_RE.search(item)
            ):
                _append(findings, "FIXTURE_NAME", item_path)
            _scan_json_value(item, item_path, findings)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_json_value(item, f"{path}[{index}]", findings)


def _scan_text(text: str, path: str, findings: List[Finding]) -> None:
    if _DOCX_NAME_RE.search(text):
        _append(findings, "DOCX_NAME", path)
    if _TEST_DOCX_RE.search(text.replace("\\", "/")):
        _append(findings, "TEST_DOCX_PATH", path)
    if _WINDOWS_ABSOLUTE_RE.search(text) or _POSIX_HOME_RE.search(text):
        _append(findings, "ABSOLUTE_PATH", path)
    if _SOURCE_HASH_RE.search(text):
        _append(findings, "SOURCE_SHA256", path)


def scan_public_metadata(paths: Iterable[Path]) -> List[Finding]:
    """Return privacy findings without echoing sensitive values."""
    findings: List[Finding] = []
    for value in paths:
        path = Path(value)
        if not path.is_file():
            _append(findings, "MISSING_FILE", str(path))
            continue
        text = path.read_text(encoding="utf-8-sig")
        display_path = path.as_posix()
        _scan_text(text, display_path, findings)
        if path.suffix.casefold() == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                _append(findings, "INVALID_JSON", display_path)
            else:
                _scan_json_value(payload, "$", findings)
    return findings


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    findings = scan_public_metadata(args.paths)
    print(json.dumps({
        "ok": not findings,
        "finding_count": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }, ensure_ascii=False, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
