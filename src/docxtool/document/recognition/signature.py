"""落款单位通用形态证据。"""

from __future__ import annotations

import re

from docxtool.document.recognition.colon import contains_colon

SIGNATURE_ORG_NEGATIVE_STARTS = ("以上", "请", "现将", "特此", "有关", "此")
SIGNATURE_ORG_SUFFIX_RE = re.compile(
    r"(?:委员会|工作委员会|人民政府|人民法院|人民检察院|代表大会|"
    r"办公室|街道办事处|领导小组|工作组|党组|党委|政府|政协|人大|"
    r"总工会|专班|小组|集团|公司|协会|学会|商会|医院|学院|学校|"
    r"大学|研究院|研究所|中心|局|厅|部|院|处|科|办|镇|乡)$"
)
SIGNATURE_BODY_CONTEXT_TYPES = (
    "body",
    "addressing",
    "attachment_note",
    "attachment_note_item",
    "attachment_body",
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


def is_body_tail_context(last_structural_type: str | None) -> bool:
    """传入上一结构类型，返回当前是否处于正文或正文后的尾部识别上下文。"""
    return last_structural_type in SIGNATURE_BODY_CONTEXT_TYPES


def blocks_independent_sign_date(previous_text: str) -> bool:
    """传入上一结构文本，返回它是否阻止当前日期作为独立尾部日期。"""
    value = (previous_text or "").strip()
    if not value:
        return False
    if value.replace(" ", "").replace("\u3000", "").startswith("责任单位："):
        return False
    if starts_with_signature_negative(value):
        return True
    return contains_colon(value)


def is_signature_org_candidate(
    text: str,
    next_text: str,
    *,
    last_structural_type: str | None,
    is_attachment_note: bool,
    current_is_sign_date: bool,
    next_is_sign_date: bool,
) -> bool:
    """传入当前行、下一行和结构事实，返回当前行是否可作为落款单位候选。"""
    value = (text or "").strip()
    if not value or len(value) > 30:
        return False
    if starts_with_signature_negative(value):
        return False
    if any(mark in value for mark in ("。", "；", ";", "：", ":")):
        return False
    if is_attachment_note or current_is_sign_date:
        return False
    if not is_body_tail_context(last_structural_type):
        return False
    if not (next_text or "").strip() or not next_is_sign_date:
        return False
    return has_signature_org_shape(value, max_length=30)
