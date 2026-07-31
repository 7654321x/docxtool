"""Offline, privacy-safe recognition comparison for DOCX files."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
logging.disable(logging.CRITICAL)

from docxtool.document.importer import DocxImporter  # noqa: E402
from docxtool.document.style_config import StyleRule  # noqa: E402


def _rules():
    return [StyleRule.default_for_row(index) for index in range(10)]


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def snapshot(path: Path, diagnostics: bool) -> dict:
    data = DocxImporter().load(
        str(path),
        _rules(),
        features={"classification": {"enabled": True}},
    )
    paragraphs = []
    for index, item in enumerate(data.paragraphs):
        meta = item.meta or {}
        paragraph = {
            "index": index,
            "text_hash": _hash(item.original_text or item.text),
            "length": len(item.original_text or item.text),
            "type": item.type_id,
            "section": meta.get("recognition_section", ""),
            "score": meta.get("recognition_confidence"),
            "style": getattr(item.features, "style_name", "") if item.features else "",
        }
        if diagnostics:
            paragraph["provider"] = meta.get("recognition_provider", "")
        paragraphs.append(paragraph)
    blocks = data.recognition_diagnostics.get("blocks", ())
    return {
        "mode": data.recognition_diagnostics.get("mode", "unknown"),
        "paragraph_count": len(data.paragraphs),
        "block_count": len(blocks),
        "table_count": sum(1 for item in blocks if item.get("kind") == "table"),
        "image_count": sum(1 for item in blocks if item.get("kind") == "image"),
        "paragraphs": paragraphs,
        "validation": data.recognition_diagnostics.get("validation", {}),
    }


def compare(runs: list[dict]) -> list[dict]:
    baseline = runs[0]
    differences = []
    for run_index, current in enumerate(runs[1:], 2):
        for field in ("mode", "paragraph_count", "block_count", "table_count", "image_count"):
            if baseline[field] != current[field]:
                differences.append(
                    {
                        "run": run_index,
                        "category": field,
                        "before": baseline[field],
                        "after": current[field],
                    }
                )
        for index, (before, after) in enumerate(zip(baseline["paragraphs"], current["paragraphs"])):
            for field in ("text_hash", "type", "section", "style"):
                if before[field] != after[field]:
                    differences.append(
                        {
                            "run": run_index,
                            "paragraph_index": index,
                            "category": field,
                            "before": before[field],
                            "after": after[field],
                        }
                    )
    return differences


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--fail-on-type-drift", action="store_true")
    parser.add_argument("--fail-on-section-drift", action="store_true")
    parser.add_argument("--fail-on-mode-drift", action="store_true")
    parser.add_argument("--fail-on-layout-drift", action="store_true")
    args = parser.parse_args()
    if args.repeat < 2:
        parser.error("--repeat must be at least 2")
    if not args.input.exists():
        parser.error("input does not exist")
    paths = (
        sorted(path for path in args.input.glob("*.docx") if not path.name.startswith("~$"))
        if args.input.is_dir()
        else [args.input]
    )
    reports = []
    execution_failed = False
    for path in paths:
        try:
            runs = [snapshot(path, args.diagnostics) for _ in range(args.repeat)]
            reports.append({"file": path.name, "runs": runs, "differences": compare(runs)})
        except Exception as exc:  # Keep directory summaries while returning execution failure.
            execution_failed = True
            reports.append({"file": path.name, "error": type(exc).__name__})
    payload = {"repeat": args.repeat, "files": reports}
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.json_output:
        args.json_output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)
    if execution_failed:
        return 3
    categories = {item["category"] for report in reports for item in report["differences"]}
    blocked = args.fail_on_type_drift and "type" in categories
    blocked = blocked or (args.fail_on_section_drift and "section" in categories)
    blocked = blocked or (args.fail_on_mode_drift and "mode" in categories)
    blocked = blocked or (args.fail_on_layout_drift and "style" in categories)
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
