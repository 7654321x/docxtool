"""识别后规范化变更账本生成。"""

from __future__ import annotations

from typing import Callable, List, Tuple

from docxtool.document.models import DocumentData, NormalizationChange

ParagraphSnapshot = Tuple[str, str, str]


def record_strict_normalization_suggestions(
    data: DocumentData,
    *,
    normalize_punctuation_func: Callable[[str], str],
) -> None:
    """记录 strict 模式下未应用的规范化建议。

    传入文档数据和标点建议函数，向 `data.normalization_changes` 追加
    未应用的标点、尾部顺序和相邻同级标题合并建议；返回值为 None，
    不修改段落正文、类型或顺序。
    """
    for index, paragraph in enumerate(data.paragraphs):
        if paragraph.type_id.startswith("__"):
            continue
        proposed = normalize_punctuation_func(paragraph.original_text)
        if proposed != paragraph.original_text:
            data.normalization_changes.append(NormalizationChange(
                paragraph_index=index,
                action="normalize_punctuation",
                before=paragraph.original_text,
                after=proposed,
                reason_code="PUNCTUATION_NORMALIZATION_SUGGESTED",
                confidence=0.9,
                applied=False,
            ))
    for index in range(len(data.paragraphs) - 2):
        current = data.paragraphs[index]
        following = data.paragraphs[index + 1]
        trailing = data.paragraphs[index + 2]
        if (
            current.type_id == "sign_org"
            and following.type_id == "sign_date"
            and trailing.type_id == "attachment_note"
        ):
            data.normalization_changes.append(NormalizationChange(
                paragraph_index=index,
                action="reorder_tail_structure",
                before="sign_org,sign_date,attachment_note",
                after="attachment_note,sign_org,sign_date",
                reason_code="TAIL_STRUCTURE_REORDER_SUGGESTED",
                confidence=0.85,
                applied=False,
            ))
    for index in range(len(data.paragraphs) - 1):
        current = data.paragraphs[index]
        following = data.paragraphs[index + 1]
        if current.type_id.startswith("heading") and current.type_id == following.type_id:
            data.normalization_changes.append(NormalizationChange(
                paragraph_index=index,
                action="merge_sibling_heading",
                before=current.original_text,
                after=f"{current.original_text}{following.original_text}",
                reason_code="SIBLING_HEADING_MERGE_SUGGESTED",
                confidence=0.7,
                applied=False,
            ))


def record_applied_normalization_changes(
    data: DocumentData,
    before: List[ParagraphSnapshot],
) -> None:
    """记录 normalize 模式已经应用的结构变化。

    传入文档数据和规范化前的 `(original_text, text, type_id)` 快照列表，
    对比当前非内部段落并追加已应用账本记录；返回值为 None，不再执行
    任何识别或规范化动作。
    """
    after = [
        (paragraph.original_text, paragraph.text, paragraph.type_id)
        for paragraph in data.paragraphs
        if not paragraph.type_id.startswith("__")
    ]
    max_length = max(len(before), len(after))
    for index in range(max_length):
        old = before[index] if index < len(before) else ("", "", "")
        new = after[index] if index < len(after) else ("", "", "")
        if old == new:
            continue
        data.normalization_changes.append(NormalizationChange(
            paragraph_index=index,
            action="normalize_structure",
            before=old[1] or old[0],
            after=new[1] or new[0],
            reason_code="LEGACY_NORMALIZATION_APPLIED",
            confidence=0.8,
            applied=True,
        ))
