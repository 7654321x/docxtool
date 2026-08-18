"""旧 importer 评分链路的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class ScoreDetail:
    """传入候选总分和来源明细，保存单个旧识别候选类型的完整评分。"""

    total: float = 0.0
    reasons: List[Tuple[str, float]] = field(default_factory=list)


@dataclass
class ScoreBoard:
    """传入候选评分增量，累计旧识别候选分数并返回胜出类型和解释链路。"""

    _scores: Dict[str, ScoreDetail] = field(default_factory=dict)

    def add_pattern(self, type_id: str, score: float) -> None:
        """传入类型和模式分数，将模式证据累加到评分面板，无返回值。"""
        self._add(type_id, "pattern", score)

    def add_rules(self, scores: Dict[str, float]) -> None:
        """传入类型到规则分数的映射，累加非零规则分数，无返回值。"""
        for type_id, score in scores.items():
            if score != 0:
                self._add(type_id, "rule", score)

    def add_context(self, type_id: str, score: float) -> None:
        """传入类型和上下文分数，将上下文证据累加到评分面板，无返回值。"""
        self._add(type_id, "context", score)

    def _add(self, type_id: str, source: str, value: float) -> None:
        """传入类型、证据来源和分值，更新内部候选总分，无返回值。"""
        if value == 0:
            return
        if type_id not in self._scores:
            self._scores[type_id] = ScoreDetail()
        self._scores[type_id].total += value
        self._scores[type_id].reasons.append((source, value))

    def winner(self) -> Tuple[str, ScoreDetail]:
        """不传参数，返回当前最高分候选；无候选时返回默认 body 候选。"""
        if not self._scores:
            detail = ScoreDetail()
            detail.total = 10.0
            detail.reasons.append(("default", 10.0))
            return ("body", detail)
        best = max(self._scores, key=lambda x: self._scores[x].total)
        return best, self._scores[best]

    def explain(self) -> List[dict]:
        """不传参数，返回按分数降序排列的结构化评分解释列表。"""
        result = []
        for type_id, detail in sorted(
            self._scores.items(), key=lambda x: x[1].total, reverse=True
        ):
            result.append({
                "type": type_id,
                "score": detail.total,
                "reasons": detail.reasons,
            })
        return result

    def debug_log(self, para_index: int, text: str, *, logger=None) -> None:
        """传入段落序号、文本和可选 logger，将评分解释写入 DEBUG 日志，无返回值。"""
        if logger is None:
            return
        logger.debug("[评分] para=%s chars=%s", para_index, len(text))
        for item in self.explain():
            parts = " + ".join(f"{s}={v:.0f}" for s, v in item["reasons"])
            logger.debug(f"  {item['type']:15} = {item['score']:5.0f}  ({parts})")


@dataclass
class DetectionContext:
    """传入旧识别遍历状态字段，保存段落识别上下文并随遍历推进更新。"""

    para_index: int = 0
    prev_type_id: str = ""
    has_seen_heading: bool = False
    has_seen_body: bool = False
    current_level: int = 0
    glossary_mode: bool = False
    title_texts: list = field(default_factory=list)
    has_seen_real_body: bool = False
    attachment_note_seen: bool = False
    attachment_note_mode: bool = False
    attachment_page_mode: bool = False
    signature_seen: bool = False
    signature_complete: bool = False
    _remaining_has_no_body: bool = False
    last_structural_type: str = ""
    last_structural_text: str = ""
    attachment_note_next_no: int = 1
