"""核心格式模型与纯配置转换。"""

from __future__ import annotations

import math
import os as _os
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from docxtool.paths import default_format_config_path
from docxtool.document.errors import ConfigValidationError

# ═══════════════════════════════════════════════════════════════
# 字号映射
# ═══════════════════════════════════════════════════════════════

FONT_SIZE_MAP: Dict[str, float] = {
    "初号": 42, "小初": 36, "一号": 26, "小一": 24,
    "二号": 22, "小二": 18, "三号": 16, "小三": 15,
    "四号": 14, "小四": 12, "五号": 10.5, "小五": 9,
    "六号": 7.5, "小六": 6.5,
}


def cn_size_to_pt(label: str) -> float:
    """中文字号标签 → pt。未知返回 12.0。"""
    return FONT_SIZE_MAP.get(label.strip(), 12.0)


# ═══════════════════════════════════════════════════════════════
# 对齐映射（python-docx 枚举值占位，实际值在 engine.py 中按需导入）
# ═══════════════════════════════════════════════════════════════

ALIGNMENT_MAP: Dict[str, str] = {
    "左对齐": "left",
    "居中": "center",
    "右对齐": "right",
    "两端对齐": "justify",
    "分散对齐": "distribute",
    "Union[奇右, 偶左]": "odd_right_even_left",
}


# ═══════════════════════════════════════════════════════════════
# 段落类型名 → type_id（rows 5-8 为被动触发型，不在 detection 中使用）
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def chinese_number(n: int) -> str:
    """Compatibility wrapper for the single Chinese integer converter."""
    from docxtool.document.engine.numbering import chinese_integer

    return chinese_integer(n)


def arabic_number(n: int) -> str:
    """阿拉伯数字 → 字符串。与 chinese_number 对称。"""
    return str(n)


def parse_indent(s: str) -> float:
    """解析缩进值。"""
    if not s or not s.strip():
        return 0.0
    s = s.strip()
    # 去掉 "字符" "磅" "cm" 等单位后缀
    s = re.sub(r'[字符磅cm].*$', '', s).strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _safe_float(value, default: float = 0.0) -> float:
    """配置数值兜底转换，兼容 JSON 数字和字符串。"""
    try:
        if value is None:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default

def finite_float(field_path: str, value, minimum: float, maximum: float) -> float:
    try:
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                raise ValueError
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(field_path, "必须是数字") from exc
    if not math.isfinite(number):
        raise ConfigValidationError(field_path, "必须是有限数字")
    if number < minimum or number > maximum:
        raise ConfigValidationError(field_path, f"必须在 {minimum:g} 到 {maximum:g} 之间")
    return number

def finite_int(field_path: str, value, minimum: int, maximum: int) -> int:
    number = finite_float(field_path, value, minimum, maximum)
    if int(number) != number:
        raise ConfigValidationError(field_path, "必须是整数")
    return int(number)

def _float_field(data: dict, key: str, field_path: str, default: float, minimum: float, maximum: float) -> float:
    if key not in data:
        return default
    return finite_float(field_path, data.get(key), minimum, maximum)

def _int_field(data: dict, key: str, field_path: str, default: int, minimum: int, maximum: int) -> int:
    if key not in data:
        return default
    return finite_int(field_path, data.get(key), minimum, maximum)

def _font_size_from_config(field_path: str, value) -> tuple[str, float]:
    if value is None:
        raise ConfigValidationError(field_path, "不能为空")
    if isinstance(value, (int, float)):
        size_pt = finite_float(field_path, value, 1.0, 72.0)
        return f"{size_pt:g}pt", size_pt
    label = str(value).strip()
    if not label:
        raise ConfigValidationError(field_path, "不能为空")
    if label in FONT_SIZE_MAP:
        return label, FONT_SIZE_MAP[label]
    try:
        numeric_label = label[:-2] if label.endswith("pt") else label
        numeric_label = numeric_label[:-1] if numeric_label.endswith("磅") else numeric_label
        size_pt = finite_float(field_path, numeric_label, 1.0, 72.0)
    except ConfigValidationError as exc:
        raise ConfigValidationError(field_path, f"未知字号 {label}") from exc
    return f"{size_pt:g}pt", size_pt


def _safe_bool(value, default: bool = False) -> bool:
    """配置布尔值兜底转换，兼容 JSON 布尔值和字符串。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "启用", "是"}:
            return True
        if normalized in {"0", "false", "no", "off", "禁用", "否"}:
            return False
    return bool(value)


def _bool_field(data: dict, key: str, field_path: str, default: bool) -> bool:
    if key not in data:
        return default
    value = data.get(key)
    if not isinstance(value, bool):
        raise ConfigValidationError(field_path, "必须是布尔值")
    return value


def _nonempty_string_field(data: dict, key: str, field_path: str, default: str) -> str:
    if key not in data:
        return default
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigValidationError(field_path, "必须是非空字符串")
    return value.strip()


def _grid_alignment(value, default: str = "文字对齐字符网络") -> str:
    """兼容旧字符串配置和新前端布尔开关。"""
    if isinstance(value, str):
        return value or default
    return default if _safe_bool(value, True) else "无"


def parse_alignment(s: str) -> Tuple[str, str]:
    """解析对齐："Union[奇右, 偶左]" → ("right", "left")，
    "左对齐" → ("left", "left")。"""
    if not s:
        return ("left", "left")
    if "|" in s:
        parts = s.split("|", 1)
        odd_part = parts[0].strip()
        even_part = parts[1].strip() if len(parts) > 1 else odd_part
        return (_to_align_id(odd_part), _to_align_id(even_part))
    return (_to_align_id(s), _to_align_id(s))


def _to_align_id(zh: str) -> str:
    mapping = {
        "左对齐": "left", "居中": "center", "右对齐": "right",
        "两端对齐": "justify", "奇右": "right", "偶左": "left",
    }
    return mapping.get(zh, "left")


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class StyleRule:
    """对应 UI 表格中一行的排版规则。"""
    row_index: int = 0
    level_name: str = ""
    font: str = "宋体"
    font_size_label: str = "三号"
    font_size_pt: float = 16.0
    bold: bool = False
    numbering_pattern: str = ""
    language: str = ""
    first_line_indent: float = 0.0
    alignment: str = "左对齐"
    spacing_before: float = 0.0
    spacing_after: float = 0.0
    left_indent: float = 0.0
    right_indent: float = 0.0
    page_break_before: bool = False

    @staticmethod
    def default_for_row(row: int) -> "StyleRule":
        """返回第 row 行的兜底默认值。"""
        defaults = [
            StyleRule(0, "主标题", "方正小标宋简体", "二号", 22.0, False, "", "中文", 0.0, "居中"),
            StyleRule(1, "一级标题", "黑体", "三号", 16.0, False, "{a}、", "中文", 2.0, "左对齐"),
            StyleRule(2, "二级标题", "楷体_GB2312", "三号", 16.0, True, "（{b}）", "中文", 2.0, "左对齐"),
            StyleRule(3, "三级标题", "仿宋_GB2312", "三号", 16.0, True, "{c}.", "阿拉伯数字", 2.0, "左对齐"),
            StyleRule(4, "四级标题", "仿宋_GB2312", "三号", 16.0, False, "（{d}）", "阿拉伯数字", 2.0, "左对齐"),
            StyleRule(5, "正文", "仿宋_GB2312", "三号", 16.0, False, "", "", 2.0, "两端对齐"),
            StyleRule(6, "数字", "Times New Roman", "三号", 16.0, False, "", "", 0.0, "左对齐"),
            StyleRule(7, "字母", "Times New Roman", "三号", 16.0, False, "", "", 0.0, "左对齐"),
            StyleRule(8, "页码设置", "宋体", "四号", 14.0, False, "— 1 —", "阿拉伯数字", 0.0, "奇右|偶左"),
            StyleRule(9, "正文上标", "Times New Roman", "三号", 16.0, False, "[n]", "阿拉伯数字", 0.0, "左对齐"),
            StyleRule(10, "称呼", "仿宋_GB2312", "三号", 16.0, False, "", "", 0.0, "左对齐", 1.0, 0.0),
            StyleRule(11, "日期行", "楷体_GB2312", "三号", 16.0, False, "", "", 0.0, "居中", 1.0, 0.0),
            StyleRule(12, "作者行", "楷体_GB2312", "三号", 16.0, True, "", "", 0.0, "居中"),
            StyleRule(13, "职务名称", "楷体_GB2312", "三号", 16.0, True, "", "", 0.0, "居中"),
            StyleRule(14, "居中小标题", "黑体", "三号", 16.0, False, "", "", 0.0, "居中", 1.0, 1.0),
            StyleRule(15, "结束语", "黑体", "三号", 16.0, False, "", "", 0.0, "居中"),
            StyleRule(16, "名词解释条目", "仿宋_GB2312", "三号", 16.0, False, "", "", 2.0, "两端对齐"),
            StyleRule(17, "附件说明", "仿宋_GB2312", "三号", 16.0, False, "", "", 0.0, "左对齐", 1.0, 0.0, 2.0),
            StyleRule(18, "附件说明续项", "仿宋_GB2312", "三号", 16.0, False, "", "", 0.0, "左对齐", 0.0, 0.0, 5.0),
            StyleRule(19, "附件正文标记", "黑体", "三号", 16.0, False, "", "", 0.0, "左对齐", 0.0, 1.0, 0.0, 0.0, True),
            StyleRule(20, "附件正文标题", "方正小标宋简体", "二号", 22.0, False, "", "", 0.0, "居中", 1.0, 1.0),
            StyleRule(21, "附件正文", "仿宋_GB2312", "三号", 16.0, False, "", "", 2.0, "两端对齐"),
            StyleRule(22, "落款署名", "仿宋_GB2312", "三号", 16.0, False, "", "", 0.0, "右对齐", 1.0, 0.0),
            StyleRule(23, "落款日期", "仿宋_GB2312", "三号", 16.0, False, "", "", 0.0, "右对齐", 0.0, 0.0, 0.0, 2.0),
        ]
        return defaults[row] if 0 <= row < len(defaults) else StyleRule()

    @staticmethod
    def from_config(config_path: str = None) -> List["StyleRule"]:
        """从默认格式配置加载排版规则（Web 服务用）。"""
        import json as _json
        if config_path is None:
            config_path = str(default_format_config_path())
        if not _os.path.exists(config_path):
            return [StyleRule.default_for_row(i) for i in range(24)]
        with open(config_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        rules = []
        for i, item in enumerate(data.get("styles", [])):
            default = StyleRule.default_for_row(i)
            rules.append(StyleRule(
                row_index=i,
                level_name=item.get("name", ""),
                font=item.get("font", "仿宋_GB2312"),
                font_size_label=item.get("size", "三号"),
                font_size_pt=cn_size_to_pt(item.get("size", "三号")),
                bold=item.get("bold", False),
                numbering_pattern=item.get("pattern", ""),
                language=item.get("lang", ""),
                first_line_indent=_safe_float(item.get("indent", default.first_line_indent), default.first_line_indent),
                alignment=item.get("align", "左对齐"),
                spacing_before=_safe_float(item.get("spacing_before", default.spacing_before), default.spacing_before),
                spacing_after=_safe_float(item.get("spacing_after", default.spacing_after), default.spacing_after),
                left_indent=_safe_float(item.get("left_indent", default.left_indent), default.left_indent),
                right_indent=_safe_float(item.get("right_indent", default.right_indent), default.right_indent),
                page_break_before=bool(item.get("page_break_before", default.page_break_before)),
            ))
        return rules

    @staticmethod
    def from_config_dict(config_dict: dict = None) -> List["StyleRule"]:
        """从前端传入的格式配置对象生成排版规则。

        不修改包内默认配置；字段缺失时按默认规则兜底，并补齐 24 行。
        """
        if not config_dict:
            return StyleRule.from_config()
        styles = config_dict.get("styles") if isinstance(config_dict, dict) else None
        if not isinstance(styles, list):
            return [StyleRule.default_for_row(i) for i in range(24)]
        rules = []
        for i in range(24):
            default = StyleRule.default_for_row(i)
            item = styles[i] if i < len(styles) and isinstance(styles[i], dict) else {}
            if "size" in item:
                size, size_pt = _font_size_from_config(f"styles[{i}].size", item.get("size"))
            else:
                size, size_pt = default.font_size_label, default.font_size_pt
            rules.append(StyleRule(
                row_index=i,
                level_name=item.get("name", default.level_name),
                font=item.get("font", default.font),
                font_size_label=size,
                font_size_pt=size_pt,
                bold=_safe_bool(item.get("bold", default.bold), default.bold),
                numbering_pattern=item.get("pattern", default.numbering_pattern),
                language=item.get("lang", default.language),
                first_line_indent=_float_field(item, "indent", f"styles[{i}].indent", default.first_line_indent, -20.0, 50.0),
                alignment=item.get("align", default.alignment),
                spacing_before=_float_field(item, "spacing_before", f"styles[{i}].spacing_before", default.spacing_before, 0.0, 20.0),
                spacing_after=_float_field(item, "spacing_after", f"styles[{i}].spacing_after", default.spacing_after, 0.0, 20.0),
                left_indent=_float_field(item, "left_indent", f"styles[{i}].left_indent", default.left_indent, 0.0, 50.0),
                right_indent=_float_field(item, "right_indent", f"styles[{i}].right_indent", default.right_indent, 0.0, 50.0),
                page_break_before=_safe_bool(item.get("page_break_before", default.page_break_before), default.page_break_before),
            ))
        return rules


@dataclass
class PageSettings:
    """页面设置。"""
    page_width_cm: float = 21.0
    page_height_cm: float = 29.7
    margin_top_cm: float = 3.7
    margin_bottom_cm: float = 3.5
    margin_left_cm: float = 2.8   # 公文标准左边界
    margin_right_cm: float = 2.6
    lines_per_page: int = 22
    chars_per_line: int = 28
    line_spacing_type: str = "固定值"
    line_spacing_value: float = 28.0
    space_before_line: float = 0.0   # 段前间距（行）
    space_after_line: float = 0.0    # 段后间距（行）
    grid_alignment: str = "文字对齐字符网络"  # 网格对齐方式

    @staticmethod
    def from_config(config_path: str = None) -> "PageSettings":
        """从默认格式配置加载页面设置。"""
        import json as _json
        if config_path is None:
            config_path = str(default_format_config_path())
        if not _os.path.exists(config_path):
            return PageSettings()
        with open(config_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        p = data.get("page", {})
        return PageSettings(
            page_width_cm=_safe_float(p.get("width_cm", 21.0), 21.0),
            page_height_cm=_safe_float(p.get("height_cm", 29.7), 29.7),
            margin_top_cm=_safe_float(p.get("margin_top_cm", 3.7), 3.7),
            margin_bottom_cm=_safe_float(p.get("margin_bottom_cm", 3.5), 3.5),
            margin_left_cm=_safe_float(p.get("margin_left_cm", 2.8), 2.8),
            margin_right_cm=_safe_float(p.get("margin_right_cm", 2.6), 2.6),
            lines_per_page=int(_safe_float(p.get("lines_per_page", 22), 22)),
            chars_per_line=int(_safe_float(p.get("chars_per_line", 28), 28)),
            line_spacing_value=_safe_float(p.get("line_spacing_pt", 28.0), 28.0),
            space_before_line=_safe_float(p.get("space_before_line", 0.0), 0.0),
            space_after_line=_safe_float(p.get("space_after_line", 0.0), 0.0),
            grid_alignment=p.get("grid_alignment", "文字对齐字符网络"),
        )

    @staticmethod
    def from_config_dict(config_dict: dict = None) -> "PageSettings":
        """从前端传入的格式配置对象生成页面设置。"""
        if not config_dict:
            return PageSettings.from_config()
        p = config_dict.get("page", {}) if isinstance(config_dict, dict) else {}
        if not isinstance(p, dict):
            p = {}
        settings = PageSettings(
            page_width_cm=_float_field(p, "width_cm", "page.width_cm", 21.0, 5.0, 100.0),
            page_height_cm=_float_field(p, "height_cm", "page.height_cm", 29.7, 5.0, 150.0),
            margin_top_cm=_float_field(p, "margin_top_cm", "page.margin_top_cm", 3.7, 0.0, 50.0),
            margin_bottom_cm=_float_field(p, "margin_bottom_cm", "page.margin_bottom_cm", 3.5, 0.0, 50.0),
            margin_left_cm=_float_field(p, "margin_left_cm", "page.margin_left_cm", 2.8, 0.0, 50.0),
            margin_right_cm=_float_field(p, "margin_right_cm", "page.margin_right_cm", 2.6, 0.0, 50.0),
            lines_per_page=_int_field(p, "lines_per_page", "page.lines_per_page", 22, 1, 200),
            chars_per_line=_int_field(p, "chars_per_line", "page.chars_per_line", 28, 1, 200),
            line_spacing_value=_float_field(p, "line_spacing_pt", "page.line_spacing_pt", 28.0, 1.0, 200.0),
            space_before_line=_float_field(p, "space_before_line", "page.space_before_line", 0.0, 0.0, 20.0),
            space_after_line=_float_field(p, "space_after_line", "page.space_after_line", 0.0, 0.0, 20.0),
            grid_alignment=_grid_alignment(p.get("grid_alignment", "文字对齐字符网络")),
        )
        validate_page_settings(settings)
        return settings


def validate_page_settings(settings: PageSettings) -> None:
    if settings.margin_left_cm + settings.margin_right_cm >= settings.page_width_cm:
        raise ConfigValidationError("page.margin_left_cm", "左右边距之和必须小于页面宽度")
    if settings.margin_top_cm + settings.margin_bottom_cm >= settings.page_height_cm:
        raise ConfigValidationError("page.margin_top_cm", "上下边距之和必须小于页面高度")
    if settings.page_width_cm - settings.margin_left_cm - settings.margin_right_cm <= 0:
        raise ConfigValidationError("page.width_cm", "可排版宽度必须大于 0")
    if settings.page_height_cm - settings.margin_top_cm - settings.margin_bottom_cm <= 0:
        raise ConfigValidationError("page.height_cm", "可排版高度必须大于 0")

# 特殊加粗匹配：数字+后缀（一是/二要/三如/…）+ 固定词组（比如：）
NB_SUFFIXES = ['是', '要']
NB_FIXED = ['比如：']
