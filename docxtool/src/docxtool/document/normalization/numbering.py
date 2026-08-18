"""识别后标题编号文本规范化辅助。"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional, Sequence, Tuple

NumberingPattern = Tuple[re.Pattern, str]
LogFunc = Callable[[str], None]


def _noop_log(_message: str) -> None:
    """默认日志回调，传入消息但不执行任何输出，返回 None。"""
    return None


def _chinese_integer(value: int) -> str:
    """将整数转为标题编号使用的中文数字。

    传入 0 到 9999 的整数，返回中文数字字符串；保持旧 importer 通过
    engine helper 得到的公开范围行为，用于识别后的编号 meta 生成。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Chinese numbering value must be an integer")
    if value < 0 or value > 9999:
        raise ValueError("Chinese numbering value must be between 0 and 9999")
    digits = "零一二三四五六七八九"
    if value < 10:
        return digits[value]
    units = ((1000, "千"), (100, "百"), (10, "十"))
    remaining = value
    pieces = []
    zero_pending = False
    for unit_value, unit_name in units:
        digit, remaining = divmod(remaining, unit_value)
        if digit:
            if zero_pending and pieces:
                pieces.append("零")
            if not (unit_value == 10 and digit == 1 and not pieces):
                pieces.append(digits[digit])
            pieces.append(unit_name)
            zero_pending = False
        elif pieces and remaining:
            zero_pending = True
    if remaining:
        if zero_pending and pieces:
            pieces.append("零")
        pieces.append(digits[remaining])
    return "".join(pieces)


def strip_numbering_prefix(
    text: str,
    prefix: Optional[str] = None,
    *,
    numbering_patterns: Sequence[NumberingPattern] = (),
) -> str:
    """剥离标题编号前缀。

    传入段落文本、可选已识别前缀和兜底编号正则，返回剥离前缀并清理
    残留点号后的标题正文；不判断段落类型，也不重建新编号。
    """
    value = text or ""
    if value.startswith("@lvl_"):
        colon = value.find(":")
        if colon > 0:
            return value[colon + 1:].strip()
    if prefix:
        value = value[len(prefix):]
    else:
        for pattern, _type_id in numbering_patterns:
            value = pattern.sub("", value, count=1)
    value = re.sub(r"^[.．、，,]\s*", "", value)
    return value.strip()


def style_key_to_rule_row(key: str) -> int:
    """将旧编号层级 key 转为样式规则行号。

    传入 `a/b/c/d` 等旧层级 key，返回样式规则行号；未知 key 返回正文
    行号 5，保持 importer 旧编号分配逻辑兼容。
    """
    return {"a": 1, "b": 2, "c": 3, "d": 4}.get(key, 5)


def assign_heading_numbering(
    paragraphs: list[Any],
    rules: Sequence[Any],
    *,
    reset_on_attach: bool = True,
    log_warning: LogFunc = _noop_log,
    log_debug: LogFunc = _noop_log,
) -> None:
    """为最终标题类型预计算可见编号。

    传入已识别段落列表、样式规则列表和附件页重置开关，按旧 importer
    的 a/b/c/d 四级计数规则写入 `paragraph.meta["numbering"]`；返回
    None，不判断段落类型、不修改正文文本。
    """
    counters = {"a": 0, "b": 0, "c": 0, "d": 0}
    level_map = {
        "heading1": "a",
        "heading2": "b",
        "heading3": "c",
        "heading4": "d",
        "glossary_item": "c",
    }

    for paragraph in paragraphs:
        if reset_on_attach and paragraph.type_id == "attachment_page_mark":
            counters = {"a": 0, "b": 0, "c": 0, "d": 0}
            continue
        if paragraph.meta.get("heading2_cont"):
            continue
        key = level_map.get(paragraph.type_id)
        if key is None:
            continue

        counters[key] += 1
        if key == "a":
            counters["b"] = counters["c"] = counters["d"] = 0
        elif key == "b":
            counters["c"] = counters["d"] = 0
        elif key == "c":
            counters["d"] = 0

        row = style_key_to_rule_row(key)
        rule = rules[row] if row < len(rules) else None
        pattern = rule.numbering_pattern if rule else ""
        if pattern and not any(char in pattern for char in ("{a}", "{b}", "{c}", "{d}")):
            fallback = {
                "a": "{a}、",
                "b": "（{b}）",
                "c": "{c}.",
                "d": "（{d}）",
            }.get(key, "")
            log_warning(f"[编号修复] pattern={pattern!r} 不包含模板变量，回退为 {fallback!r}")
            pattern = fallback

        use_chinese = paragraph.type_id in ("heading1", "heading2")
        number_func = _chinese_integer if use_chinese else str
        log_debug(f"[编号渲染] pattern={pattern!r} a={counters['a']} is_cn={use_chinese}")
        result = pattern
        result = result.replace("{a}", number_func(counters["a"]))
        result = result.replace("{b}", number_func(counters["b"]))
        result = result.replace("{c}", str(counters["c"]))
        result = result.replace("{d}", str(counters["d"]))

        paragraph.meta["numbering"] = result
        log_debug(
            f"[编号] {paragraph.type_id} → \"{result}\" "
            f"(a={counters['a']} b={counters['b']} c={counters['c']} d={counters['d']})"
        )


def fix_heading_numbering_gaps(
    paragraphs: list[Any],
    *,
    log_warning: LogFunc = _noop_log,
) -> None:
    """修复已生成标题编号中的连续性跳号。

    传入已识别段落列表，读取 `type_id` 和 `meta["numbering"]`，按旧
    importer 的期望序列原地修正 heading1-4 的编号 meta；返回 None，
    不改变段落类型、文本或顺序。
    """
    cn_to_int = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    int_to_cn = {value: key for key, value in cn_to_int.items()}
    expected = {"a": 1, "b": {}, "c": {}, "d": {}}

    for paragraph in paragraphs:
        if paragraph.type_id == "attachment_page_mark":
            expected = {"a": 1, "b": {}, "c": {}, "d": {}}
            continue
        type_id = paragraph.type_id
        if type_id not in ("heading1", "heading2", "heading3", "heading4"):
            continue
        key = type_id[-1]
        number = paragraph.meta.get("numbering", "")
        if not number:
            continue

        if key == "1":
            char = number[0]
            actual = cn_to_int.get(char)
            if actual and actual != expected["a"]:
                fixed = int_to_cn.get(expected["a"], str(expected["a"]))
                paragraph.meta["numbering"] = number.replace(char + "、", fixed + "、", 1)
                log_warning(f"[编号修正] heading1 {number}→{paragraph.meta['numbering']}")
                actual = expected["a"]
            if actual:
                expected["a"] = actual + 1
                expected["b"] = {actual: 1}
                expected["c"] = {}
                expected["d"] = {}
        elif key == "2":
            parent_a = expected["a"] - 1
            char = number[1] if number.startswith("（") else number[0]
            actual = cn_to_int.get(char)
            expected_number = expected["b"].get(parent_a, 1)
            if actual and actual != expected_number:
                fixed = int_to_cn.get(expected_number, str(expected_number))
                paragraph.meta["numbering"] = number.replace(
                    "（" + char + "）", "（" + fixed + "）", 1
                ).replace(char + ".", fixed + ".", 1)
                log_warning(f"[编号修正] heading2 {number}→{paragraph.meta['numbering']}")
                actual = expected_number
            if actual:
                expected["b"][parent_a] = actual + 1
            expected["c"] = {}
            expected["d"] = {}
        elif key == "3":
            parent_a = expected["a"] - 1
            parent_b = expected["b"].get(parent_a, 1) - 1
            index = (parent_a, parent_b)
            actual = int(number.rstrip(".")) if number.rstrip(".").isdigit() else None
            expected_number = expected["c"].get(index, 1)
            if actual is not None and actual != expected_number:
                paragraph.meta["numbering"] = str(expected_number) + "."
                log_warning(f"[编号修正] heading3 {number}→{paragraph.meta['numbering']}")
                actual = expected_number
            if actual is not None:
                expected["c"][index] = actual + 1
            expected["d"] = {}
        elif key == "4":
            parent_a = expected["a"] - 1
            parent_b = expected["b"].get(parent_a, 1) - 1
            parent_c = expected["c"].get((parent_a, parent_b), 1) - 1
            index = (parent_a, parent_b, parent_c)
            match = re.search(r"\d+", number)
            actual = int(match.group()) if match else None
            expected_number = expected["d"].get(index, 1)
            if actual is not None and actual != expected_number:
                paragraph.meta["numbering"] = number.replace(str(actual), str(expected_number), 1)
                log_warning(f"[编号修正] heading4 {number}→{paragraph.meta['numbering']}")
                actual = expected_number
            if actual is not None:
                expected["d"][index] = actual + 1
