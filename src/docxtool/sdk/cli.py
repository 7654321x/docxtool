"""Command-line adapters for the local recognition SDK."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .binding import bind_recognition_plan
from .errors import DocxToolSdkError
from .manifest import get_sdk_manifest
from .models import RecognitionRequest, summarize_host_snapshot
from .recognition import recognize_docx
from .validation import (
    host_snapshot_from_dict,
    recognition_request_from_dict,
    validate_host_snapshot,
    validate_recognition_binding,
    validate_recognition_plan,
    validate_sdk_manifest,
    validate_recognition_request,
)


def _json_read(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _data_or_payload(value: Mapping[str, Any]) -> Mapping[str, Any]:
    data = value.get("data") if isinstance(value, Mapping) else None
    return data if isinstance(data, Mapping) else value


def _write_payload(payload: Mapping[str, Any], output: Optional[Path]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def _error(exc: BaseException) -> dict:
    if isinstance(exc, DocxToolSdkError):
        payload = exc.to_dict()
    else:
        payload = {
            "schema_version": "sdk-error-v1",
            "code": getattr(exc, "code", "INVALID_RECOGNITION_REQUEST"),
            "message": "SDK 请求处理失败",
            "retryable": False,
            "details": {},
        }
    return {"ok": False, "error": payload}


def _legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recognize a DOCX file and write a redacted JSON plan.")
    parser.add_argument("source", type=Path, help="Input .docx path")
    parser.add_argument("--output", "-o", type=Path, help="JSON output path; defaults to stdout")
    parser.add_argument("--config", type=Path, help="Optional Docxtool format-config JSON path")
    parser.add_argument("--mode", choices=("strict", "structural", "normalize"), default="structural")
    parser.add_argument("--recognition-mode", choices=("legacy", "shadow", "authoritative"), default="authoritative")
    parser.add_argument("--include-text", action="store_true", help="Include block text for a local-only consumer")
    parser.add_argument("--include-raw-text", action="store_true", help="Include raw source fragments; local-only")
    parser.add_argument("--host-snapshot", type=Path, help="Optional local host snapshot JSON to bind against the plan")
    return parser


def recognize_main(argv: Optional[Sequence[str]] = None) -> int:
    args = _legacy_parser().parse_args(argv)
    try:
        request = RecognitionRequest(
            processing_mode=args.mode,
            recognition_mode=args.recognition_mode,
            format_config=_json_read(args.config) if args.config else None,
            include_text=args.include_text,
            include_raw_text=args.include_raw_text,
        )
        plan = recognize_docx(args.source, request=request)
        response = _ok(plan.to_dict())
        if args.host_snapshot:
            response["binding"] = bind_recognition_plan(plan, _json_read(args.host_snapshot)).to_dict()
    except (OSError, TypeError, ValueError, DocxToolSdkError) as exc:
        _write_payload(_error(exc), args.output)
        return 2
    _write_payload(response, args.output)
    return 0


def _sdk_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DocxTool SDK JSON protocol CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser("manifest", help="Print SDK manifest.")
    manifest.add_argument("--output", "-o", type=Path)

    recognize = subparsers.add_parser("recognize", help="Recognize a DOCX snapshot.")
    recognize.add_argument("--source", required=True, type=Path)
    recognize.add_argument("--request", type=Path, help="RecognitionRequest JSON; defaults to v1 defaults")
    recognize.add_argument("--output", "-o", type=Path)
    recognize.add_argument("--strict", action="store_true", help="Reject unknown extension fields.")

    bind = subparsers.add_parser("bind", help="Bind a saved RecognitionPlan to a HostSnapshot.")
    bind.add_argument("--plan", required=True, type=Path)
    bind.add_argument("--snapshot", required=True, type=Path)
    bind.add_argument("--output", "-o", type=Path)
    bind.add_argument("--strict", action="store_true", help="Reject unknown extension fields.")

    validate = subparsers.add_parser("validate", help="Validate a public SDK JSON object.")
    validate.add_argument("--kind", required=True, choices=(
        "manifest",
        "recognition-request",
        "recognition-plan",
        "host-snapshot",
        "recognition-binding",
    ))
    validate.add_argument("--input", required=True, type=Path)
    validate.add_argument("--output", "-o", type=Path)
    validate.add_argument("--strict", action="store_true", help="Reject unknown extension fields.")

    summary = subparsers.add_parser("summarize-snapshot", help="Write a text-free HostSnapshot summary.")
    summary.add_argument("--snapshot", required=True, type=Path)
    summary.add_argument("--output", "-o", type=Path)
    summary.add_argument("--strict", action="store_true", help="Reject unknown extension fields.")
    return parser


def sdk_main(argv: Optional[Sequence[str]] = None) -> int:
    args = _sdk_parser().parse_args(argv)
    try:
        if args.command == "manifest":
            _write_payload(_ok(get_sdk_manifest().to_dict()), args.output)
            return 0
        if args.command == "recognize":
            request = (
                recognition_request_from_dict(_data_or_payload(_json_read(args.request)), strict=args.strict)
                if args.request else RecognitionRequest()
            )
            plan = recognize_docx(args.source, request=request)
            _write_payload(_ok(plan.to_dict()), args.output)
            return 0
        if args.command == "bind":
            binding = bind_recognition_plan(
                _data_or_payload(_json_read(args.plan)),
                _data_or_payload(_json_read(args.snapshot)),
                strict=args.strict,
            )
            _write_payload(_ok(binding.to_dict()), args.output)
            return 0
        if args.command == "validate":
            payload = _data_or_payload(_json_read(args.input))
            if args.kind == "manifest":
                report = validate_sdk_manifest(payload, strict=args.strict)
            elif args.kind == "recognition-request":
                report = validate_recognition_request(payload, strict=args.strict)
            elif args.kind == "recognition-plan":
                report = validate_recognition_plan(payload, strict=args.strict)
            elif args.kind == "host-snapshot":
                report = validate_host_snapshot(payload, strict=args.strict)
            else:
                report = validate_recognition_binding(payload, strict=args.strict)
            _write_payload(_ok({"kind": args.kind, **report.to_dict()}), args.output)
            return 0 if report.valid else 1
        if args.command == "summarize-snapshot":
            snapshot = host_snapshot_from_dict(_data_or_payload(_json_read(args.snapshot)), strict=args.strict)
            _write_payload(_ok(summarize_host_snapshot(snapshot).to_dict()), args.output)
            return 0
    except (OSError, TypeError, ValueError, DocxToolSdkError) as exc:
        _write_payload(_error(exc), getattr(args, "output", None))
        return 2
    _write_payload(_error(DocxToolSdkError("未知命令", code="INVALID_RECOGNITION_REQUEST")), None)
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Universal entry point with legacy recognize compatibility."""
    arguments = list(argv if argv is not None else sys.argv[1:])
    if not arguments or arguments[0] in {
        "manifest", "recognize", "bind", "validate", "summarize-snapshot", "-h", "--help"
    }:
        return sdk_main(arguments)
    return recognize_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
