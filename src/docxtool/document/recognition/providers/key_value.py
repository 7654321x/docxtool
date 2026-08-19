"""Key-value candidate provider."""

from __future__ import annotations

from ..colon import is_organization_label
from ..model import ParagraphType, SectionKind
from .base import Candidate


_EMPTY_KEY_VALUE_LABELS = frozenset({
    "责任单位", "责任人", "联系人", "联系电话", "联系地址",
    "承办单位", "牵头单位", "配合单位", "时间", "地点",
})


class KeyValueCandidateProvider:
    name = "key-value"

    def propose(self, block, features, context):
        if features.numbered_heading2_colon_inline_body:
            return []
        label = features.key_value_label or ""
        if not label:
            return []
        if is_organization_label(label):
            return []
        if not str(features.key_value_value or "").strip() and label not in _EMPTY_KEY_VALUE_LABELS:
            return []
        if label in {"时间", "地点", "主持", "记录", "出席", "缺席", "列席", "参会", "参加", "议题", "议定事项", "会议名称", "会议时间", "会议地点"}:
            return [Candidate(ParagraphType.MEETING_META, 0.99, self.name, ("meeting-label",), section_hint=SectionKind.MEETING_META)]
        if (
            any(char.isdigit() for char in label)
            or any(mark in label for mark in "。！？；;（）()[]〔〕")
            or "附件" in label
        ):
            return []
        return [Candidate(ParagraphType.KEY_VALUE, 0.92, self.name, ("explicit-label",), section_hint=SectionKind.BODY)]
