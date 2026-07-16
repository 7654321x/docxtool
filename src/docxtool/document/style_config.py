"""style_config — 排版规则、页面设置、日志。

职责边界：
  - StyleRule / PageSettings 数据模型 + 默认值
  - default-format.json 读取（Web 端）+ UI 表格读取（桌面端）
  - 中文数字/字号/对齐等纯函数转换
  - PyQt5 可选依赖（桌面端），Web 端通过 from_config() 替代
"""

import logging
import math
import os as _os
import re

from docxtool.paths import default_format_config_path
import contextvars
from datetime import datetime
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional, Tuple

try:
    from PyQt5.QtWidgets import QTableWidget, QWidget, QTextEdit
except ImportError:
    QTableWidget = QWidget = QTextEdit = None  # Web 端不需要 PyQt5

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

ROW_NAMES: List[str] = [
    "一级标题", "二级标题", "三级标题", "四级标题",
    "正文", "数字", "字母", "页码设置", "正文上标",
]


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

_CHINESE_DIGITS = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
                   "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十"]


def chinese_number(n: int) -> str:
    """阿拉伯数字 → 中文数字。1→"一", 12→"十二", 20→"二十", 21→"二十一"。"""
    if 0 <= n <= 20:
        return _CHINESE_DIGITS[n]
    tens = n // 10
    ones = n % 10
    return _CHINESE_DIGITS[tens] + "十" + (_CHINESE_DIGITS[ones] if ones else "")


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

class ConfigValidationError(ValueError):
    def __init__(self, field_path: str, reason: str):
        self.code = "FORMAT_CONFIG_INVALID"
        self.field = field_path
        self.reason = reason
        super().__init__(f"{self.code}: {field_path}: {reason}")

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
        size_pt = finite_float(field_path, label.removesuffix("pt").removesuffix("磅"), 1.0, 72.0)
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
# 异常体系
# ═══════════════════════════════════════════════════════════════

class FormatterError(Exception):
    """所有排版相关异常的基类。"""
    pass


class ImportError(FormatterError):
    """文档导入阶段异常。"""
    pass


class StyleError(FormatterError):
    """样式应用阶段异常。"""
    pass


class ExportError(FormatterError):
    """文档导出阶段异常。"""
    pass


# ═══════════════════════════════════════════════════════════════
# 统一日志接口
# ═══════════════════════════════════════════════════════════════

LOGGER_NAME = "docx_tool"
LOG_FORMAT = "%(asctime)s [%(levelname)-5s] %(name)s | %(message)s"
LOG_TO_FILE = True                     # 全局开关：True=写日志文件，False=仅控制台
_LOG_DIR: Optional[str] = None         # 日志输出目录（由 Web 服务启动时配置）
_FILE_HANDLER: Optional[logging.Handler] = None
_CONTEXT_FILE_HANDLER: Optional[logging.Handler] = None
_CURRENT_LOG_PATH: Optional[str] = None
_CONTEXT_LOG_PATH = contextvars.ContextVar("docx_tool_context_log_path", default="")
_MAX_LOG_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 5


def _sanitize_log_stem(filepath: str) -> str:
    """Return a Windows-safe log filename stem while preserving readable Chinese."""
    stem = _os.path.splitext(_os.path.basename(str(filepath or "")))[0].strip()
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" ._")
    return (stem or "document")[:80]


def _build_document_log_path(filepath: str, log_dir: str = None,
                             timestamp: str = None, suffix: str = "") -> str:
    root = log_dir or _LOG_DIR or _os.path.join(_os.getcwd(), "logs")
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = _sanitize_log_stem(filepath)
    safe_suffix = _sanitize_log_stem(suffix) if suffix else ""
    suffix_part = f"_{safe_suffix}" if safe_suffix else ""
    return _os.path.join(root, f"{ts}_{stem}{suffix_part}.log")


def make_document_log_path(filepath: str, log_dir: str = None,
                           suffix: str = "") -> str:
    """Build a per-document log path without changing active handlers."""
    return _build_document_log_path(filepath, log_dir=log_dir, suffix=suffix)


class _ContextFileHandler(logging.Handler):
    """Write records to the log path stored in the current execution context."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.setFormatter(logging.Formatter(LOG_FORMAT))

    def emit(self, record):
        log_path = _CONTEXT_LOG_PATH.get("")
        if not log_path:
            return
        try:
            msg = self.format(record)
            _os.makedirs(_os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            self.handleError(record)


def _ensure_console_handler(logger: logging.Logger) -> None:
    if any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
           for h in logger.handlers):
        return
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(ch)


def _ensure_context_file_handler(logger: logging.Logger) -> None:
    global _CONTEXT_FILE_HANDLER
    if _CONTEXT_FILE_HANDLER is not None:
        return
    _CONTEXT_FILE_HANDLER = _ContextFileHandler()
    logger.addHandler(_CONTEXT_FILE_HANDLER)


def _set_file_handler(log_path: str) -> str:
    global _FILE_HANDLER, _CURRENT_LOG_PATH
    logger = logging.getLogger(LOGGER_NAME)
    _ensure_console_handler(logger)
    if _FILE_HANDLER is not None:
        logger.removeHandler(_FILE_HANDLER)
        try:
            _FILE_HANDLER.close()
        except Exception:
            pass
    _os.makedirs(_os.path.dirname(log_path), exist_ok=True)
    handler = RotatingFileHandler(
        log_path, maxBytes=_MAX_LOG_BYTES, backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8"
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    _FILE_HANDLER = handler
    _CURRENT_LOG_PATH = log_path
    return log_path


def configure_logging(log_dir: str, to_file: bool = True) -> None:
    """设置日志输出目录和文件开关（Web 服务启动时调用一次）。"""
    global LOG_TO_FILE, _LOG_DIR
    LOG_TO_FILE = to_file
    _LOG_DIR = log_dir


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    """获取统一 logger：控制台全级 + 文件 DEBUG（如果开关开启）。"""
    global _FILE_HANDLER
    logger = logging.getLogger(name)

    # 控制台 handler（只加一次）
    _ensure_console_handler(logger)
    _ensure_context_file_handler(logger)

    # 文件 handler（按开关动态添加/移除）
    if LOG_TO_FILE and _LOG_DIR and _FILE_HANDLER is None:
        try:
            log_path = _os.path.join(_LOG_DIR, "公文排版工具.log")
            _set_file_handler(log_path)
            logger.info(f"日志文件: {log_path}")
        except Exception as e:
            logger.warning(f"无法创建日志文件: {e}")
    elif not LOG_TO_FILE and _FILE_HANDLER is not None:
        logger.removeHandler(_FILE_HANDLER)
        _FILE_HANDLER = None

    return logger


def start_document_log(filepath: str, suffix: str = "") -> str:
    """Switch file logging to a per-document log and return the log path."""
    if not LOG_TO_FILE:
        return ""
    log_path = _build_document_log_path(filepath, suffix=suffix)
    try:
        _set_file_handler(log_path)
        logging.getLogger(LOGGER_NAME).info(f"[日志] 文档日志: {log_path}")
        return log_path
    except Exception as e:
        logging.getLogger(LOGGER_NAME).warning(f"[日志] 文档日志创建失败: {e}")
        return ""


def set_context_log_path(log_path: str):
    """Route logs emitted in this execution context to log_path."""
    return _CONTEXT_LOG_PATH.set(log_path or "")


def reset_context_log_path(token) -> None:
    """Restore the previous context log path."""
    _CONTEXT_LOG_PATH.reset(token)


def close_file_log() -> None:
    """Close the active file log handler. Mainly useful for tests and shutdown."""
    global _FILE_HANDLER, _CURRENT_LOG_PATH
    if _FILE_HANDLER is None:
        return
    logger = logging.getLogger(LOGGER_NAME)
    logger.removeHandler(_FILE_HANDLER)
    try:
        _FILE_HANDLER.close()
    finally:
        _FILE_HANDLER = None
        _CURRENT_LOG_PATH = None


logger = get_logger()


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
            StyleRule(20, "附件正文标题", "方正小标宋简体", "二号", 22.0, False, "", "", 0.0, "居中"),
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

def validate_format_config(config_dict: dict) -> dict:
    if not isinstance(config_dict, dict):
        raise ConfigValidationError("config", "必须是 JSON 对象")
    StyleRule.from_config_dict(config_dict)
    PageSettings.from_config_dict(config_dict)
    _parse_core_feature_options(config_dict)
    normalized = dict(config_dict)
    if config_dict.get("letterhead") is not None:
        from docxtool.document.letterhead_config import normalize_letterhead_config

        normalized["letterhead"] = normalize_letterhead_config(config_dict["letterhead"])
    return normalized


def _safe_mode(field_path: str, value, allowed: set[str], default: str) -> str:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        raise ConfigValidationError(field_path, f"必须是 {', '.join(sorted(allowed))} 之一")
    return normalized


def _dict_field(config_dict: dict, key: str) -> dict:
    value = config_dict.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        legacy_enabled = _legacy_feature_enabled(key, value)
        if legacy_enabled is not None:
            return {"enabled": legacy_enabled}
        raise ConfigValidationError(key, "必须是对象或布尔值")
    return value


def _legacy_feature_enabled(field_path: str, value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on", "启用", "是"}:
            return True
        if raw in {"0", "false", "no", "off", "禁用", "否"}:
            return False
    return None


def _scope_options(field_path: str, value) -> dict:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ConfigValidationError(field_path, "必须是对象")
    return {
        "body": _safe_bool(value.get("body", True), True),
        "tables": _safe_bool(value.get("tables", False), False),
        "headers": _safe_bool(value.get("headers", False), False),
        "footers": _safe_bool(value.get("footers", False), False),
    }


def _parse_core_feature_options(config_dict: dict) -> dict:
    punctuation = _dict_field(config_dict, "punctuation")
    classification = _dict_field(config_dict, "classification")
    numbering = _dict_field(config_dict, "numbering")
    page_number = _dict_field(config_dict, "page_number")
    signature_block = _dict_field(config_dict, "signature_block")
    table_format = _dict_field(config_dict, "table_format")
    cleanup = _dict_field(config_dict, "cleanup")
    raw_features = config_dict.get("features", {})
    legacy_page_number_enabled = None
    if isinstance(raw_features, dict) and "page_number_enabled" in raw_features:
        legacy_page_number_enabled = _safe_bool(raw_features.get("page_number_enabled"), True)
    if "enabled" in page_number:
        page_number_enabled = _bool_field(page_number, "enabled", "page_number.enabled", True)
    elif legacy_page_number_enabled is not None:
        page_number_enabled = legacy_page_number_enabled
    else:
        page_number_enabled = True
    return {
        "punctuation": {
            "enabled": _safe_bool(punctuation.get("enabled", False), False),
            "mode": _safe_mode("punctuation.mode", punctuation.get("mode", "safe"), {"off", "safe", "standard"}, "safe"),
            "scope": _scope_options("punctuation.scope", punctuation.get("scope", {})),
        },
        "classification": {
            "enabled": _safe_bool(classification.get("enabled", True), True),
            "minimum_auto_format_confidence": finite_float(
                "classification.minimum_auto_format_confidence",
                classification.get("minimum_auto_format_confidence", 0.85),
                0,
                1,
            ),
        },
        "numbering": {
            "enabled": _safe_bool(numbering.get("enabled", False), False),
            "mode": _safe_mode("numbering.mode", numbering.get("mode", "safe"), {"off", "safe"}, "safe"),
        },
        "page_number": {
            "enabled": page_number_enabled,
            "font_name": _nonempty_string_field(
                page_number, "font_name", "page_number.font_name", "宋体"
            ),
            "font_size_pt": finite_float(
                "page_number.font_size_pt",
                page_number.get("font_size_pt", 14),
                1,
                72,
            ),
            "bold": _bool_field(page_number, "bold", "page_number.bold", False),
            "style": _safe_mode(
                "page_number.style",
                page_number.get("style", "dash"),
                {"plain", "number", "page", "dash", "cn", "chinese", "cn_total", "chinese_total", "page_numpages"},
                "dash",
            ),
            "position": _safe_mode(
                "page_number.position",
                page_number.get("position", "outside"),
                {"left", "center", "centre", "right", "outside"},
                "outside",
            ),
            "first_page": _bool_field(
                page_number, "first_page", "page_number.first_page", True
            ),
            "section_numbering": _safe_mode(
                "page_number.section_numbering",
                page_number.get("section_numbering", "continue"),
                {"continue", "restart", "restart_each_section", "new"},
                "continue",
            ),
            "offset_from_text_mm": finite_float(
                "page_number.offset_from_text_mm",
                page_number.get("offset_from_text_mm", 7),
                0,
                30,
            ),
        },
        "signature_block": {
            "mode": _safe_mode(
                "signature_block.mode",
                signature_block.get("mode", "preserve"),
                {"preserve", "without_seal", "with_seal"},
                "preserve",
            ),
        },
        "table_format": {
            "enabled": _safe_bool(table_format.get("enabled", False), False),
            "smart_alignment": _safe_bool(table_format.get("smart_alignment", False), False),
        },
        "cleanup": {
            "enabled": _safe_bool(cleanup.get("enabled", False), False),
            "mode": _safe_mode("cleanup.mode", cleanup.get("mode", "safe"), {"off", "safe"}, "safe"),
        },
    }

def load_rules_and_settings(config_dict: dict = None):
    """加载本次任务的 rules/settings/features。

    config_dict 为空时使用服务器默认格式配置；不为空时只对当前任务生效。
    """
    if config_dict:
        rules = StyleRule.from_config_dict(config_dict)
        settings = PageSettings.from_config_dict(config_dict)
        raw_features = config_dict.get("features", {}) if isinstance(config_dict, dict) else {}
        if not isinstance(raw_features, dict):
            raw_features = {}
    else:
        rules = StyleRule.from_config()
        settings = PageSettings.from_config()
        raw_features = {}
    features = {
        "numbered_bold_enabled": _safe_bool(raw_features.get("numbered_bold_enabled", True), True),
        "punctuation_enabled": _safe_bool(raw_features.get("punctuation_enabled", True), True),
        "page_number_enabled": _safe_bool(raw_features.get("page_number_enabled", True), True),
    }
    if isinstance(config_dict, dict):
        features.update(_parse_core_feature_options(config_dict))
        from docxtool.document.letterhead_config import normalize_letterhead_config

        features["letterhead"] = normalize_letterhead_config(config_dict.get("letterhead"))
    else:
        features.update(_parse_core_feature_options({}))
        from docxtool.document.letterhead_config import default_letterhead_config

        features["letterhead"] = default_letterhead_config()
    return rules, settings, features


# ═══════════════════════════════════════════════════════════════
# 表格列索引常量
# ═══════════════════════════════════════════════════════════════

# 特殊加粗匹配：数字+后缀（一是/二要/三如/…）+ 固定词组（比如：）
NB_SUFFIXES = ['是', '要']        # → "X是" "X要"
NB_FIXED = ['比如：']             # → "比如：" 直接匹配

COL_FONT = 0       # 字体
COL_SIZE = 1       # 字号
COL_BOLD = 2       # 加粗（存储 "True"/"False" 字符串）
COL_PATTERN = 3    # 样式/编号模板
COL_LANG = 4       # 语言
COL_INDENT = 5     # 首行缩进
COL_ALIGN = 6      # 对齐方式


# ═══════════════════════════════════════════════════════════════
# UI 表格读取
# ═══════════════════════════════════════════════════════════════

def read_rules_from_table(table) -> List[StyleRule]:
    """遍历 QTableWidget（9行×7列），返回 9 条 StyleRule。
    Web 端 PyQt5 不可用时返回空列表。"""
    if QTableWidget is None:
        return []
    # 防御逻辑：
    #   - 单元格为空 → 使用该行的兜底默认值
    #   - 字号无法映射 → 默认 12pt 并 logger.warning
    #   - 对齐格式错误 → 默认左对齐并 logger.warning
    #   - 任何异常 → 不崩溃，返回带默认值的 StyleRule
    rules: List[StyleRule] = []
    for row in range(table.rowCount()):
        try:
            default = StyleRule.default_for_row(row)
            font = _safe_cell_text(table, row, COL_FONT, default.font)
            size_label = _safe_cell_text(table, row, COL_SIZE, default.font_size_label)
            bold_str = _safe_cell_text(table, row, COL_BOLD, str(default.bold))
            pattern = _safe_cell_text(table, row, COL_PATTERN, default.numbering_pattern)
            # 自动修复：裸字母 a/b/c/d 补花括号（兼容旧 UI 不规范的输入）
            for ch, brace in [("a", "{a}"), ("b", "{b}"), ("c", "{c}"), ("d", "{d}")]:
                if brace not in pattern and ch in pattern:
                    pattern = pattern.replace(ch, brace)
            lang = _safe_cell_text(table, row, COL_LANG, default.language)
            indent_str = _safe_cell_text(table, row, COL_INDENT,
                                         str(default.first_line_indent) + "字符")
            align_str = _safe_cell_text(table, row, COL_ALIGN, default.alignment)

            # 转换
            size_pt = cn_size_to_pt(size_label)
            if size_pt == 12.0 and size_label.strip() not in ("", "12pt", "小四"):
                # 12.0 是 cn_size_to_pt 的兜底值，确认是否真的匹配
                if size_label.strip() not in FONT_SIZE_MAP:
                    logger.warning(f"[config] 行{row} 字号 '{size_label}' 无法识别，使用兜底 {default.font_size_label}")
                    size_pt = default.font_size_pt

            bold = bold_str.strip().lower() in ("true", "是", "1", "加粗")
            indent = parse_indent(indent_str)
            name = ROW_NAMES[row] if row < len(ROW_NAMES) else f"行{row}"

            rule = StyleRule(
                row_index=row,
                level_name=name,
                font=font,
                font_size_label=size_label,
                font_size_pt=size_pt,
                bold=bold,
                numbering_pattern=pattern,
                language=lang,
                first_line_indent=indent,
                alignment=align_str,
            )
            rules.append(rule)
        except Exception as e:
            logger.warning(f"[config] 行{row} 读取失败: {e}，使用兜底默认值")
            rules.append(StyleRule.default_for_row(row))
    return rules


def _safe_cell_text(table, row: int, col: int, fallback: str) -> str:
    """Safe cell text read, returns fallback on empty or error."""
    try:
        item = table.item(row, col)
        if item is None or item.text() is None:
            return fallback
        text = item.text().strip()
        return text if text else fallback
    except Exception:
        return fallback


def read_page_settings(form: QWidget) -> PageSettings:
    """从 Form 的 QTextEdit 控件读取页面设置。

    控件映射：
      textEdit     → margin_top_cm
      textEdit_2   → margin_bottom_cm
      textEdit_3   → margin_left_cm
      textEdit_4   → margin_right_cm
      textEdit_5   → lines_per_page
      textEdit_6   → chars_per_line
      textEdit_7   → line_spacing_value
      textEdit_8   → grid_alignment
      textEdit_10  → space_before_line
      textEdit_11  → space_after_line
    """
    try:
        top = _parse_cm(form, "textEdit", 3.7)
        bottom = _parse_cm(form, "textEdit_2", 3.5)
        left = _parse_cm(form, "textEdit_3", 2.8)
        right = _parse_cm(form, "textEdit_4", 2.6)
    except Exception as e:
        logger.warning(f"[config] 页边距读取失败: {e}")
        top = bottom = left = right = 2.5

    lines = _parse_int(form, "textEdit_5", 22)
    chars = _parse_int(form, "textEdit_6", 28)
    spacing_val = _parse_pt(form, "textEdit_7", 28.0)
    grid_align = _parse_text(form, "textEdit_8", "文字对齐字符网络")
    space_before = _parse_line(form, "textEdit_10", 0.0)
    space_after = _parse_line(form, "textEdit_11", 0.0)

    return PageSettings(
        margin_top_cm=top, margin_bottom_cm=bottom,
        margin_left_cm=left, margin_right_cm=right,
        lines_per_page=lines, chars_per_line=chars,
        line_spacing_type="固定值", line_spacing_value=spacing_val,
        space_before_line=space_before, space_after_line=space_after,
        grid_alignment=grid_align,
    )


def _parse_cm(form: QWidget, name: str, default: float) -> float:
    """从 QTextEdit 读取以 cm 结尾的数值。"""
    text = _parse_text(form, name, str(default))
    text = re.sub(r'[cC][mM].*$', '', text).strip()
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


def _parse_int(form: QWidget, name: str, default: int) -> int:
    """从 QTextEdit 读取整数。"""
    text = _parse_text(form, name, str(default))
    text = re.sub(r'[^0-9\-]', '', text).strip()
    try:
        return int(text)
    except (ValueError, TypeError):
        return default


def _parse_line(form: QWidget, name: str, default: float) -> float:
    """从 QTextEdit 读取以"行"结尾的数值。"""
    text = _parse_text(form, name, str(default))
    text = re.sub(r'[行].*$', '', text).strip()
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


def _parse_pt(form: QWidget, name: str, default: float) -> float:
    """从 QTextEdit 读取以磅结尾的数值。"""
    text = _parse_text(form, name, str(default))
    text = re.sub(r'[磅pP][tT]?.*$', '', text).strip()
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


def _parse_text(form: QWidget, name: str, default: str) -> str:
    """从 form 中按 objectName 查找 QTextEdit 并读取纯文本。"""
    try:
        widget = form.findChild(QTextEdit, name)
        if widget is None:
            return default
        text = widget.toPlainText().strip()
        return text if text else default
    except Exception:
        return default


# ═══════════════════════════════════════════════════════════════
# 验证
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 单元验证：不依赖 UI 的纯函数
    assert cn_size_to_pt("三号") == 16.0, "cn_size_to_pt 失败"
    assert cn_size_to_pt("二号") == 22.0, "cn_size_to_pt 二号失败"
    assert cn_size_to_pt("未知") == 12.0, "cn_size_to_pt 未知应返回 12.0"
    assert chinese_number(1) == "一", "chinese_number(1) 失败"
    assert chinese_number(12) == "十二", "chinese_number(12) 失败"
    assert chinese_number(21) == "二十一", "chinese_number(21) 失败"
    assert arabic_number(5) == "5", "arabic_number 失败"
    assert parse_indent("2字符") == 2.0, "parse_indent('2字符') 失败"
    assert parse_indent("28磅") == 28.0, "parse_indent('28磅') 失败"
    assert parse_indent("") == 0.0, "parse_indent('') 失败"
    assert parse_indent(None) == 0.0, "parse_indent(None) 失败"
    assert parse_alignment("左对齐") == ("left", "left"), "parse_alignment 左对齐 失败"
    assert parse_alignment("Union[奇右, 偶左]") == ("right", "left"), "parse_alignment Union[奇右, 偶左] 失败"
    assert parse_alignment("") == ("left", "left"), "parse_alignment 空字符串 失败"
    assert StyleRule.default_for_row(0).font == "方正小标宋简体"
    assert StyleRule.default_for_row(5).font == "仿宋_GB2312"
    assert StyleRule.default_for_row(8).font_size_pt == 14.0
    assert _sanitize_log_stem("新建 DOCX 文档 (2).docx") == "新建 DOCX 文档 (2)"
    assert _sanitize_log_stem('a<b>:c?.docx') == "a_b_c"
    assert _build_document_log_path(
        r"C:\Users\94575\Desktop\新建 DOCX 文档 (2).docx",
        r"D:\logs",
        timestamp="20260531_160000",
    ).endswith(r"D:\logs\20260531_160000_新建 DOCX 文档 (2).log")

    print("✅ 样式配置纯函数验证全部通过")
