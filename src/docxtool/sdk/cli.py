"""Command-line adapter for the local recognition SDK."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .recognition import RecognitionSdkError, recognize_docx


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recognize a DOCX file and write a redacted JSON plan.")
    parser.add_argument("source", type=Path, help="Input .docx path")
    parser.add_argument("--output", "-o", type=Path, help="JSON output path; defaults to stdout")
    parser.add_argument("--config", type=Path, help="Optional Docxtool format-config JSON path")
    parser.add_argument("--mode", choices=("strict", "structural", "normalize"), default="structural")
    parser.add_argument("--recognition-mode", choices=("legacy", "shadow", "authoritative"), default="authoritative")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        format_config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else None
        plan = recognize_docx(
            args.source,
            processing_mode=args.mode,
            recognition_mode=args.recognition_mode,
            format_config=format_config,
        )
    except (OSError, ValueError, RecognitionSdkError) as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}}, ensure_ascii=False))
        return 2
    payload = json.dumps({"ok": True, "data": plan.to_dict()}, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
