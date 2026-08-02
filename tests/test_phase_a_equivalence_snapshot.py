from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Dict, Iterable, Mapping, Tuple
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "phase_a_equivalence_snapshot.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("phase_a_equivalence_snapshot", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


snapshot = _load_script()


CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="bin" ContentType="application/octet-stream"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>
"""


def _relationship_xml(items: Iterable[Tuple[str, str, str, str]]) -> bytes:
    rows = []
    for relationship_id, relationship_type, target, target_mode in items:
        mode = ' TargetMode="{0}"'.format(target_mode) if target_mode else ""
        rows.append(
            '<Relationship Id="{0}" Type="{1}" Target="{2}"{3}/>'.format(
                relationship_id,
                relationship_type,
                target,
                mode,
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rows)
        + "</Relationships>"
    ).encode("utf-8")


def _write_package(
    path: Path,
    parts: Mapping[str, bytes],
    *,
    relationships: Mapping[str, bytes] | None = None,
    reverse_order: bool = False,
    timestamp: Tuple[int, int, int, int, int, int] = (2024, 1, 1, 0, 0, 0),
) -> None:
    entries: Dict[str, bytes] = {"[Content_Types].xml": CONTENT_TYPES}
    entries.update(parts)
    entries.update(relationships or {})
    names = sorted(entries, reverse=reverse_order)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, entries[name])


def _core_properties(created: str, modified: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dcterms:created xsi:type="dcterms:W3CDTF">{0}</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">{1}</dcterms:modified>'
        '</cp:coreProperties>'
    ).format(created, modified).encode("utf-8")


def _manifest_payload(manifest: dict) -> dict:
    return {
        "documents": [
            {
                "modes": {
                    "strict": {
                        "export": {
                            "package_manifest": manifest,
                        }
                    }
                }
            }
        ]
    }


def test_package_manifest_detects_image_and_embedded_object_changes(tmp_path: Path) -> None:
    first = tmp_path / "first.docx"
    second = tmp_path / "second.docx"
    common = {"word/document.xml": b"<document/>"}
    _write_package(
        first,
        {
            **common,
            "word/media/image1.png": b"image-a",
            "word/embeddings/object1.bin": b"object-a",
        },
    )
    _write_package(
        second,
        {
            **common,
            "word/media/image1.png": b"image-b",
            "word/embeddings/object1.bin": b"object-b",
        },
    )

    first_manifest = snapshot._package_manifest(first)
    paths = snapshot._difference_paths(first_manifest, snapshot._package_manifest(second))

    assert any("word/media/image1.png" in path for path in paths)
    assert any("word/embeddings/object1.bin" in path for path in paths)
    assert first_manifest["parts"]["word/media/image1.png"]["content_type"] == "image/png"
    assert (
        first_manifest["parts"]["word/embeddings/object1.bin"]["content_type"]
        == "application/octet-stream"
    )


def test_package_manifest_records_missing_internal_relationship_target(tmp_path: Path) -> None:
    package_path = tmp_path / "missing-target.docx"
    _write_package(
        package_path,
        {"word/document.xml": b"<document/>"},
        relationships={
            "word/_rels/document.xml.rels": _relationship_xml(
                (("rId1", "image", "media/missing.png", ""),)
            )
        },
    )

    manifest = snapshot._package_manifest(package_path)
    relationship = manifest["relationships"]["word/document.xml|rId1"]

    assert relationship["target_exists"] is False
    assert manifest["valid"] is False
    assert manifest["missing_relationship_target_count"] == 1


def test_compare_never_reports_identical_invalid_packages_as_equivalent(tmp_path: Path) -> None:
    package_path = tmp_path / "invalid.docx"
    _write_package(
        package_path,
        {"word/document.xml": b"<document/>"},
        relationships={
            "word/_rels/document.xml.rels": _relationship_xml(
                (("rId1", "image", "media/missing.png", ""),)
            )
        },
    )
    payload = _manifest_payload(snapshot._package_manifest(package_path))
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    report = tmp_path / "report.json"
    before.write_text(json.dumps(payload), encoding="utf-8")
    after.write_text(json.dumps(payload), encoding="utf-8")

    comparison = snapshot.compare_snapshots(before, after, report)

    assert comparison["difference_count"] > 0
    assert comparison["relationship_differences"]


def test_compare_reports_header_relationship_target_and_part_set_changes(tmp_path: Path) -> None:
    first = tmp_path / "header-a.docx"
    second = tmp_path / "header-b.docx"
    _write_package(
        first,
        {
            "word/document.xml": b"<document/>",
            "word/header1.xml": b"<header/>",
            "word/media/a.png": b"a",
        },
        relationships={
            "word/_rels/header1.xml.rels": _relationship_xml(
                (("rId7", "image", "media/a.png", ""),)
            )
        },
    )
    _write_package(
        second,
        {
            "word/document.xml": b"<document/>",
            "word/header1.xml": b"<header/>",
            "word/media/b.png": b"b",
            "word/theme/theme1.xml": b"<theme/>",
        },
        relationships={
            "word/_rels/header1.xml.rels": _relationship_xml(
                (("rId7", "image", "media/b.png", ""),)
            )
        },
    )
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    report = tmp_path / "report.json"
    before.write_text(json.dumps(_manifest_payload(snapshot._package_manifest(first))), encoding="utf-8")
    after.write_text(json.dumps(_manifest_payload(snapshot._package_manifest(second))), encoding="utf-8")

    comparison = snapshot.compare_snapshots(before, after, report)

    assert comparison["package_part_differences"]
    assert comparison["relationship_differences"]
    assert comparison["document_structure_differences"] == []


def test_package_manifest_ignores_zip_order_timestamp_and_allowed_core_times(tmp_path: Path) -> None:
    first = tmp_path / "ordered.docx"
    second = tmp_path / "reordered.docx"
    first_parts = {
        "word/document.xml": b"<document/>",
        "docProps/core.xml": _core_properties(
            "2024-01-01T00:00:00Z",
            "2024-01-02T00:00:00Z",
        ),
    }
    second_parts = {
        "word/document.xml": b"<document/>",
        "docProps/core.xml": _core_properties(
            "2026-08-01T08:30:00Z",
            "2026-08-02T09:45:00Z",
        ),
    }
    _write_package(first, first_parts, timestamp=(2024, 1, 1, 0, 0, 0))
    _write_package(
        second,
        second_parts,
        reverse_order=True,
        timestamp=(2026, 8, 2, 12, 0, 0),
    )

    first_manifest = snapshot._package_manifest(first)
    second_manifest = snapshot._package_manifest(second)

    assert first_manifest == second_manifest
    assert first_manifest["normalized_metadata"] == [
        {
            "fields": ["created", "modified"],
            "part_name": "docProps/core.xml",
            "strategy": "replace-core-property-time-text",
        }
    ]


def _captured_case(final_type: str, candidate_digest: str, *, input_type: str = "body") -> dict:
    return {
        "pre_recognition": {
            "paragraphs": [
                {
                    "type_id": input_type,
                    "legacy_type_id": "heading1",
                    "text": {"length": 4, "sha256": "text-hash"},
                }
            ]
        },
        "result": {
            "paragraphs": [
                {
                    "type_id": final_type,
                    "final_type": final_type,
                    "review_level": "confirmed",
                }
            ],
            "diagnostics": {
                "paragraphs": [
                    {
                        "final_type": final_type,
                        "candidate_digest": candidate_digest,
                    }
                ]
            },
        },
    }


def test_legacy_provider_comparison_separates_input_invariance_from_output_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(snapshot, "MODES", ("strict",))
    monkeypatch.setattr(snapshot, "_document_sources", lambda: [("fixture", Path("sample.docx"))])

    def fake_load(_source, _mode, _rules, *, legacy_candidates_enabled=None):
        captured = (
            _captured_case("heading1", "enabled")
            if legacy_candidates_enabled
            else _captured_case("body", "disabled")
        )
        return captured, object()

    monkeypatch.setattr(snapshot, "_load_with_capture", fake_load)

    payload = snapshot.capture_legacy_provider_comparison(tmp_path / "provider.json")

    assert payload["input_comparison"]["difference_count"] == 0
    assert payload["output_comparison"]["difference_count"] > 0
    assert payload["legacy_candidate_provider"]["status"] == "toggled"
    assert payload["importer_legacy_preprocessing"]["status"] == "blocked"
    assert payload["importer_legacy_preprocessing"]["enabled_in_both_runs"] is True
    assert payload["importer_legacy_preprocessing"]["tested"] is False
    assert "does not disable importer Legacy preprocessing" in payload["scope_warning"]


def test_legacy_provider_comparison_detects_pre_recognition_input_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(snapshot, "MODES", ("strict",))
    monkeypatch.setattr(snapshot, "_document_sources", lambda: [("fixture", Path("sample.docx"))])

    def fake_load(_source, _mode, _rules, *, legacy_candidates_enabled=None):
        input_type = "heading1" if legacy_candidates_enabled else "body"
        return _captured_case("body", "same", input_type=input_type), object()

    monkeypatch.setattr(snapshot, "_load_with_capture", fake_load)

    payload = snapshot.capture_legacy_provider_comparison(tmp_path / "provider.json")

    assert payload["input_comparison"]["difference_count"] == 1
    assert payload["input_comparison"]["differences"][0]["fields"] == [
        "$.paragraphs[0].type_id"
    ]


def test_legacy_input_cli_alias_matches_new_command_and_warns(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    def fake_capture(output: Path) -> dict:
        payload = {
            "input_comparison": {"difference_count": 0},
            "output_comparison": {"difference_count": 1},
        }
        output.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return payload

    monkeypatch.setattr(snapshot, "capture_legacy_provider_comparison", fake_capture)
    new_output = tmp_path / "new.json"
    alias_output = tmp_path / "alias.json"

    assert snapshot.main(
        ["legacy-provider-input-invariance", "--output", str(new_output)]
    ) == 0
    assert snapshot.main(["legacy-input", "--output", str(alias_output)]) == 0
    assert json.loads(new_output.read_text(encoding="utf-8")) == json.loads(
        alias_output.read_text(encoding="utf-8")
    )
    assert "deprecated" in capsys.readouterr().err.lower()


def test_legacy_provider_cli_returns_one_only_for_input_drift(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "provider.json"

    monkeypatch.setattr(
        snapshot,
        "capture_legacy_provider_comparison",
        lambda _output: {
            "input_comparison": {"difference_count": 1},
            "output_comparison": {"difference_count": 0},
        },
    )

    assert snapshot.main(
        ["legacy-provider-input-invariance", "--output", str(output)]
    ) == 1
