"""落款单位通用形态证据。"""

from __future__ import annotations

import re

SIGNATURE_ORG_NEGATIVE_STARTS = ("以上", "请", "现将", "特此", "有关", "此")
SIGNATURE_ORG_SUFFIX_RE = re.compile(
    r"(?:委员会|工作委员会|人民政府|人民法院|人民检察院|代表大会|"
    r"办公室|街道办事处|领导小组|工作组|党组|党委|政府|政协|人大|"
    r"总工会|专班|小组|集团|公司|协会|学会|商会|医院|学院|学校|"
    r"大学|研究院|研究所|中心|局|厅|部|院|处|科|办|镇|乡)$"
)


def starts_with_signature_negative(text: str) -> bool:
    """传入候选文本，返回是否以前置否定语开头而不应作为落款单位。"""
    return (text or "").strip().startswith(SIGNATURE_ORG_NEGATIVE_STARTS)


def has_signature_org_shape(text: str, *, max_length: int = 40) -> bool:
    """传入短行文本，返回是否具备通用落款单位形态；不判断上下文或最终类型。"""
    value = (text or "").strip()
    return bool(
        2 <= len(value) <= max_length
        and not starts_with_signature_negative(value)
        and not any(mark in value for mark in "。；;：:")
        and bool(SIGNATURE_ORG_SUFFIX_RE.search(value))
    )
