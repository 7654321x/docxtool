"""Audit letterhead detection for the numbered batch without storing正文."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
logging.disable(logging.CRITICAL)

from docxtool.document.importer import DocxImporter  # noqa: E402
from docxtool.document.style_config import StyleRule  # noqa: E402
from batch_test_docx import physical_snapshot  # noqa: E402


INPUT = ROOT / "test_docx" / "strat_docx"
OUTPUT = ROOT / "test_docx" / "end_docx"
TEMPLATE = ROOT / "test_docx" / "correct_docx" / "005班子对照检查材料_正确格式.docx"


def inspect(path: Path, importer: DocxImporter, rules: list[StyleRule]) -> dict:
    data = importer.load(str(path), rules)
    detection = data.letterhead_detection
    return {
        "文件名": path.name,
        "版头状态": detection.status,
        "版头详情": list(detection.details),
        "版头段落数": sum(item.type_id == "__letterhead__" for item in data.paragraphs),
        "发文字号数": sum(item.type_id == "dispatch_number" for item in data.paragraphs),
        "前五段类型": [item.type_id for item in data.paragraphs[:5]],
        "段落数": len(data.paragraphs),
    }


def main() -> int:
    importer = DocxImporter()
    rules = StyleRule.from_config()
    outputs = sorted(OUTPUT.glob("*_排版结果.docx"))
    records = [inspect(path, importer, rules) for path in outputs]
    no_head = [item for item in records if item["版头状态"] == "none"]
    template_physical = physical_snapshot(TEMPLATE)
    template_physical["paragraphs"] = [
        item for item in template_physical["paragraphs"][8:]
        if not (item["length"] == 0 and item["style"] == "Docxtool Role Name")
    ]
    compare_fields = (
        "text_hash", "length", "style", "font", "size_pt", "bold", "alignment",
        "first_indent", "left_indent", "right_indent", "line_spacing", "space_before",
        "space_after", "page_break_before", "keep_with_next", "keep_together",
    )
    aligned_counts: dict[str, int] = {}
    aligned_files: dict[str, int] = {}
    for path in sorted(OUTPUT.glob("*_排版结果.docx")):
        actual = physical_snapshot(path)
        differences = [
            field
            for actual_item, expected_item in zip(actual["paragraphs"], template_physical["paragraphs"])
            for field in compare_fields
            if actual_item.get(field) != expected_item.get(field)
        ]
        if differences:
            aligned_files[path.name[:3]] = len(differences)
            for field in differences:
                aligned_counts[field] = aligned_counts.get(field, 0) + 1
    report = {
        "总数": len(records),
        "无版头数": len(no_head),
        "版头状态统计": {status: sum(item["版头状态"] == status for item in records) for status in sorted({item["版头状态"] for item in records})},
        "无版头文件": no_head,
        "问题归类": [
            {"问题": "测试输入本身没有版头信号", "影响": "50 篇输入均没有结构化发文字号、版头段或可识别红线信号，检测器按规范返回 none。"},
            {"问题": "排版批处理未启用版头生成配置", "影响": "调用 export_doc 时未传入 letterhead_options，因此没有根据标准模板主动生成版头。"},
            {"问题": "批处理报告字段误判", "影响": "旧报告使用 bool(letterhead_detection)，对象存在即为 True，不能代表检测状态；应使用 detection.status。"},
            {"问题": "标准模板与输出结构不同", "影响": "标准模板含版头段落，输出保留原始标题流，模板差异被记录为核心结构差异。"},
        ],
        "模板": TEMPLATE.name if TEMPLATE.exists() else "缺失",
        "去除版头错位后的非版头差异": {
            "有差异文件数": len(aligned_files),
            "字段差异统计": aligned_counts,
            "文件差异数量": aligned_files,
            "说明": "已移除模板前 8 个版头段和 1 个空职务段后再比较；这些差异不再包含版头造成的索引错位。",
        },
        "视觉渲染检查": "未执行",
    }
    batch_report_path = OUTPUT / "批量测试报告.json"
    if batch_report_path.exists():
        batch_report = json.loads(batch_report_path.read_text(encoding="utf-8"))
        by_name = {item["文件名"]: item for item in records}
        for item in batch_report.get("结果", []):
            detected = by_name.get(item.get("输出文件名"))
            if detected:
                item.pop("版头", None)
                item.update({
                    "版头状态": detected["版头状态"],
                    "版头详情": detected["版头详情"],
                    "版头段落数": detected["版头段落数"],
                    "发文字号数": detected["发文字号数"],
                })
        batch_report_path.write_text(json.dumps(batch_report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT / "无版头问题分析.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"总数：{report['总数']}",
        f"无版头数：{report['无版头数']}",
        f"版头状态统计：{json.dumps(report['版头状态统计'], ensure_ascii=False)}",
        f"去除版头错位后仍有非版头差异的文件：{report['去除版头错位后的非版头差异']['有差异文件数']}",
        f"非版头字段差异：{json.dumps(report['去除版头错位后的非版头差异']['字段差异统计'], ensure_ascii=False)}",
        "",
        "问题归类：",
    ]
    lines.extend(f"- {item['问题']}：{item['影响']}" for item in report["问题归类"])
    lines.extend(["", "无版头文件："])
    lines.extend(f"- {item['文件名']} | 状态={item['版头状态']} | 版头段落={item['版头段落数']} | 发文字号={item['发文字号数']}" for item in no_head)
    lines.append("视觉渲染检查：未执行")
    (OUTPUT / "无版头问题分析.txt").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"total": len(records), "no_letterhead": len(no_head), "report": str(OUTPUT / '无版头问题分析.json')}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
