"""Run all numbered DOCX fixtures and compare results with a correct template."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import time
import zipfile

from docx import Document

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from docxtool.document.engine import export_doc  # noqa: E402
from docxtool.document.importer import DocxImporter  # noqa: E402
from docxtool.document.style_config import PageSettings, StyleRule  # noqa: E402

INPUT_DIR = ROOT / "test_docx" / "strat_docx"
TEMPLATE_DIR = ROOT / "test_docx" / "correct_docx"
OUTPUT_DIR = ROOT / "test_docx" / "end_docx"


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def first_run(paragraph):
    for run in paragraph.runs:
        if run.text.strip():
            return run
    return paragraph.runs[0] if paragraph.runs else None


def physical_snapshot(path: Path) -> dict:
    document = Document(path)
    paragraphs = []
    for index, paragraph in enumerate(document.paragraphs):
        run = first_run(paragraph)
        fmt = paragraph.paragraph_format
        paragraphs.append({
            "index": index,
            "text_hash": text_hash(paragraph.text),
            "length": len(paragraph.text),
            "style": paragraph.style.name if paragraph.style else "",
            "font": run.font.name if run else "",
            "size_pt": round(run.font.size.pt, 3) if run and run.font.size else None,
            "bold": bool(run.bold) if run else False,
            "italic": bool(run.italic) if run else False,
            "underline": bool(run.underline) if run else False,
            "alignment": str(paragraph.alignment) if paragraph.alignment is not None else "",
            "first_indent": int(fmt.first_line_indent) if fmt.first_line_indent else 0,
            "left_indent": int(fmt.left_indent) if fmt.left_indent else 0,
            "right_indent": int(fmt.right_indent) if fmt.right_indent else 0,
            "line_spacing": str(fmt.line_spacing) if fmt.line_spacing is not None else "",
            "space_before": int(fmt.space_before) if fmt.space_before else 0,
            "space_after": int(fmt.space_after) if fmt.space_after else 0,
            "page_break_before": bool(fmt.page_break_before),
            "keep_with_next": bool(fmt.keep_with_next),
            "keep_together": bool(fmt.keep_together),
        })
    return {
        "paragraphs": paragraphs,
        "tables": len(document.tables),
        "sections": len(document.sections),
        "inline_shapes": len(document.inline_shapes),
        "headers": sum(len(section.header.paragraphs) for section in document.sections),
        "footers": sum(len(section.footer.paragraphs) for section in document.sections),
    }


def recognition_snapshot(path: Path, rules: list[StyleRule]) -> dict:
    data = DocxImporter().load(str(path), rules, features={"classification": {"enabled": True}})
    paragraphs = []
    for index, item in enumerate(data.paragraphs):
        features = item.features
        paragraphs.append({
            "index": index,
            "text_hash": text_hash(item.original_text or item.text),
            "length": len(item.original_text or item.text),
            "type": item.type_id,
            "recognition_type": item.meta.get("recognition_type", ""),
            "section": item.meta.get("recognition_section", ""),
            "heading_level": _heading_level(item.type_id),
            "font": features.font_name if features else "",
            "size_pt": features.font_size_pt if features else None,
            "bold": bool(features.bold) if features else False,
            "alignment": features.alignment if features else "",
            "first_indent": features.first_line_indent if features else 0,
            "style": features.style_name if features else "",
        })
    diagnostics = getattr(data, "recognition_diagnostics", {}) or {}
    return {
        "mode": data.doc_mode,
        "paragraphs": paragraphs,
        "tables": len(data.tables),
        "blocks": len(getattr(data, "body_blocks", []) or []),
        "images": sum(1 for item in paragraphs if item.get("contains_image")),
        "diagnostic_summary": diagnostics.get("summary", {}),
    }


def _heading_level(type_id: str):
    match = re.fullmatch(r"heading([1-4])(?:_report)?", type_id or "")
    return int(match.group(1)) if match else None


def template_for(source: Path) -> tuple[Path | None, str]:
    templates = sorted(TEMPLATE_DIR.glob("*.docx"))
    if not templates:
        return None, "无模板"
    match = re.match(r"^(\d{3})_", source.name)
    if match:
        numbered = [path for path in templates if path.name.startswith(match.group(1) + "_")]
        if len(numbered) == 1:
            return numbered[0], "编号匹配"
        if len(numbered) > 1:
            return None, "编号模板不唯一"
    if len(templates) == 1:
        return templates[0], "单模板统一对照"
    return None, "模板匹配不明确"


def diff_snapshots(actual: dict, expected: dict) -> list[dict]:
    differences = []
    for field in ("mode", "tables", "blocks", "images"):
        if actual.get(field) != expected.get(field):
            differences.append({"category": field, "actual": actual.get(field), "expected": expected.get(field), "paragraph_index": None})
    actual_paragraphs = actual.get("paragraphs", [])
    expected_paragraphs = expected.get("paragraphs", [])
    if len(actual_paragraphs) != len(expected_paragraphs):
        differences.append({"category": "paragraph_count", "actual": len(actual_paragraphs), "expected": len(expected_paragraphs), "paragraph_index": None})
    fields = ("text_hash", "length", "type", "recognition_type", "section", "heading_level", "font", "size_pt", "bold", "alignment", "first_indent", "style")
    for index, (actual_item, expected_item) in enumerate(zip(actual_paragraphs, expected_paragraphs)):
        for field in fields:
            if actual_item.get(field) != expected_item.get(field):
                differences.append({"category": field, "actual": actual_item.get(field), "expected": expected_item.get(field), "paragraph_index": index})
    return differences


def severity(category: str) -> str:
    if category in {"paragraph_count", "text_hash", "length", "mode", "tables", "images", "blocks"}:
        return "P1"
    if category in {"type", "recognition_type", "section", "heading_level"}:
        return "P1"
    if category in {"font", "size_pt", "bold", "alignment", "first_indent", "style"}:
        return "P2"
    return "P3"


def main() -> int:
    sources = sorted(INPUT_DIR.glob("*.docx"))
    if len(sources) != 50:
        raise SystemExit(f"expected 50 input DOCX files, found {len(sources)}")
    existing = list(OUTPUT_DIR.glob("*.docx"))
    if existing:
        raise SystemExit(f"output directory is not empty: {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rules = StyleRule.from_config()
    settings = PageSettings.from_config()
    importer = DocxImporter()
    results = []
    for source in sources:
        start = time.perf_counter()
        output = OUTPUT_DIR / source.name.replace("_乱格式测试.docx", "_排版结果.docx")
        temporary = OUTPUT_DIR / f".{output.stem}.tmp.docx"
        template, template_status = template_for(source)
        record = {"编号": source.name[:3], "原始文件名": source.name, "输出文件名": output.name, "模板": template.name if template else "", "模板匹配": template_status, "成功": False, "错误": "", "差异": [], "耗时_ms": 0}
        try:
            source_data = importer.load(str(source), rules)
            export_doc(source_data, rules, settings, str(temporary))
            with zipfile.ZipFile(temporary) as package:
                bad_member = package.testzip()
                if bad_member:
                    raise ValueError(f"ZIP_INTEGRITY:{bad_member}")
            temporary.replace(output)
            output_data = importer.load(str(output), rules)
            record.update({
                "成功": True,
                "原文段落数": len(source_data.paragraphs),
                "输出段落数": len(output_data.paragraphs),
                "输出模式": output_data.doc_mode,
                "版头状态": output_data.letterhead_detection.status if output_data.letterhead_detection else "none",
                "版头详情": list(output_data.letterhead_detection.details) if output_data.letterhead_detection else [],
                "版头段落数": sum(item.type_id == "__letterhead__" for item in output_data.paragraphs),
                "发文字号数": sum(item.type_id == "dispatch_number" for item in output_data.paragraphs),
                "表格数": len(output_data.tables),
                "结构诊断": (getattr(output_data, "recognition_diagnostics", {}) or {}).get("summary", {}),
            })
            if template:
                actual = {"recognition": recognition_snapshot(output, rules), "physical": physical_snapshot(output)}
                expected = {"recognition": recognition_snapshot(template, rules), "physical": physical_snapshot(template)}
                diffs = diff_snapshots(actual["recognition"], expected["recognition"])
                diffs.extend(diff_snapshots(actual["physical"], expected["physical"]))
                record["差异"] = [{**item, "severity": severity(item["category"])} for item in diffs]
            record["原文文字哈希"] = text_hash("\n".join(item.original_text for item in source_data.paragraphs))
            record["输出文字哈希"] = text_hash("\n".join(item.original_text for item in output_data.paragraphs))
        except Exception as exc:
            record["错误"] = f"{type(exc).__name__}: {exc}"
            if temporary.exists():
                temporary.unlink()
        record["耗时_ms"] = round((time.perf_counter() - start) * 1000, 2)
        results.append(record)
    report = {"总数": len(results), "成功数": sum(bool(item["成功"]) for item in results), "失败数": sum(not item["成功"] for item in results), "差异文件数": sum(bool(item["差异"]) for item in results), "问题统计": {level: sum(1 for item in results for diff in item["差异"] if diff["severity"] == level) for level in ("P0", "P1", "P2", "P3")}, "结果": results}
    (OUTPUT_DIR / "批量测试报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"总数：{report['总数']}", f"成功：{report['成功数']}", f"失败：{report['失败数']}", f"存在模板差异的文件：{report['差异文件数']}", "问题统计：" + json.dumps(report["问题统计"], ensure_ascii=False)]
    for item in results:
        lines.append(f"{item['编号']} {item['原始文件名']} | 成功={item['成功']} | 差异={len(item['差异'])} | 错误={item['错误']}")
    (OUTPUT_DIR / "批量测试报告.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0 if report["失败数"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
