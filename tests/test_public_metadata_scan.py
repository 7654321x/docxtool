from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_public_metadata.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_public_metadata", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scanner():
    return _load_script()


@pytest.mark.parametrize(
    ("suffix", "payload", "expected_code"),
    [
        (".json", {"source_name": "005会议讲话.docx"}, "DOCX_NAME"),
        (".md", "报告位于 test_docx/output/report.json", "TEST_DOCX_PATH"),
        (".md", r"本地文件 D:\private\source.json", "ABSOLUTE_PATH"),
        (".md", "本地文件 /home/user/source.json", "ABSOLUTE_PATH"),
        (".json", {"source_sha256": "a" * 64}, "SOURCE_SHA256"),
        (".json", {"fixture_name": "在专题会议上的讲话"}, "FIXTURE_NAME"),
    ],
)
def test_public_metadata_scanner_rejects_sensitive_fixture_metadata(
    tmp_path: Path,
    scanner,
    suffix: str,
    payload,
    expected_code: str,
) -> None:
    path = tmp_path / f"public{suffix}"
    if suffix == ".json":
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(payload, encoding="utf-8")

    findings = scanner.scan_public_metadata([path])

    assert expected_code in {item.code for item in findings}


def test_public_metadata_scanner_allows_release_hashes_and_anonymous_ids(
    tmp_path: Path,
    scanner,
) -> None:
    path = tmp_path / "public.json"
    path.write_text(
        json.dumps({
            "fixtures": [
                {"id": "standard-001", "category": "standard"},
                {"id": "special-role-date-001", "category": "role-date"},
                {"id": "special-attachment-001", "category": "attachment"},
            ],
            "commit_sha": "1" * 40,
            "tree_sha": "2" * 40,
            "wheel_sha256": "3" * 64,
            "output_aggregate_sha256": "4" * 64,
            "config_sha256": "5" * 64,
        }),
        encoding="utf-8",
    )

    assert scanner.scan_public_metadata([path]) == []


def test_checked_phase_b0_public_files_pass_metadata_scan(scanner) -> None:
    paths = [
        ROOT / "docs" / "migration" / "phase-b0-manifest.json",
        ROOT / "docs" / "migration" / "phase-b0-report.md",
    ]

    assert scanner.scan_public_metadata(paths) == []
