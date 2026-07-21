"""Repeatable, file-free recognition benchmark."""

from __future__ import annotations

import argparse
import gc
import json
import platform
from pathlib import Path
from statistics import fmean, median, pstdev
import sys
from time import perf_counter_ns
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from docxtool.document.recognition import RecognitionConfig, apply_recognition, extract_blocks, extract_features  # noqa: E402
from docxtool.document.recognition.features import detect_mode  # noqa: E402
from docxtool.document.recognition.version import RECOGNITION_VERSION_TAG  # noqa: E402


def _document(count: int):
    paragraphs = []
    for index in range(count):
        if index == 0:
            text, type_id = "关于公共服务工作的通知", "title"
        elif index == 1:
            text, type_id = "测发〔2026〕23号", "title_cont"
        elif index % 25 == 0:
            text, type_id = f"{index // 25}、阶段工作", "heading1"
        else:
            text, type_id = f"第{index}段工作内容，说明现状并提出具体措施。", "body"
        features = SimpleNamespace(paragraph_index=index, alignment="", style_name="", bold=False, font_size_pt=None)
        paragraphs.append(SimpleNamespace(text=text, original_text=text, type_id=type_id, features=features, meta={}, inline_tokens=[]))
    return SimpleNamespace(paragraphs=paragraphs, tables=[], doc_mode="NORMAL")


def run_once(count: int, diagnostics: bool) -> dict:
    data = _document(count)  # Deliberately outside the measured interval.
    stamps = [perf_counter_ns()]
    blocks = extract_blocks(data)
    stamps.append(perf_counter_ns())
    visible = [item for item in blocks if item.paragraph_index is not None]
    features = [extract_features(item, visible[index - 1] if index else None, visible[index + 1] if index + 1 < len(visible) else None) for index, item in enumerate(visible)]
    stamps.append(perf_counter_ns())
    detect_mode(features, data.doc_mode)
    stamps.append(perf_counter_ns())
    config = RecognitionConfig(enable_diagnostics=diagnostics)
    apply_recognition(data, config)
    stamps.append(perf_counter_ns())
    names = ("block_extraction", "feature_extraction", "mode_detection", "decode_validate_structure")
    timing = {name: (stamps[index + 1] - stamps[index]) / 1_000_000 for index, name in enumerate(names)}
    timing["total"] = (stamps[-1] - stamps[0]) / 1_000_000
    trace = data.recognition_diagnostics.get("candidate_trace", ())
    counts = [item["candidate_count"] for item in trace]
    return {"timing_ms": timing, "average_candidates": fmean(counts) if counts else None, "maximum_candidates": max(counts, default=None), "beam_width": config.beam_width}


def _stats(values: list[float]) -> dict:
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * 0.9 + 0.5)))]
    return {"min": round(ordered[0], 3), "median": round(median(ordered), 3), "mean": round(fmean(ordered), 3), "p90": round(p90, 3), "stddev": round(pstdev(ordered), 3)}


def benchmark(count: int, diagnostics: bool, repeats: int) -> dict:
    samples = []
    for _ in range(2):
        gc.collect()
        run_once(count, diagnostics)
    for _ in range(repeats):
        gc.collect()
        samples.append(run_once(count, diagnostics))
    phases = samples[0]["timing_ms"]
    return {"paragraphs": count, "diagnostics": diagnostics, "repeats": repeats, "timing_ms": {name: _stats([sample["timing_ms"][name] for sample in samples]) for name in phases}, "average_candidates": samples[-1]["average_candidates"], "maximum_candidates": samples[-1]["maximum_candidates"], "configured_beam_width": samples[-1]["beam_width"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    if args.repeats < 7:
        parser.error("--repeats must be at least 7")
    results = []
    # Fixed alternating order avoids consistently favoring one diagnostic mode.
    for count in (25, 200, 800):
        for diagnostics in (False, True):
            results.append(benchmark(count, diagnostics, args.repeats))
    payload = {"benchmark": RECOGNITION_VERSION_TAG, "python": platform.python_version(), "platform": platform.system(), "results": results}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
