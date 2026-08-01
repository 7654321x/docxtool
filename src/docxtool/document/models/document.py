"""Document-level models shared across import, normalization, and rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from docxtool.document.models.paragraph import ParagraphData


@dataclass
class BodyBlock:
    """记录导出时需要保持的原始 body 顺序块。

    传入数据是块类型和块对象。返回值是可变块模型，用于把段落、表格和原始
    XML 节点按源文档顺序交给渲染器。
    """

    kind: str
    value: object


@dataclass
class DocumentData:
    """记录一次 DOCX 导入后的完整中间文档。

    传入数据是段落、表格、body 顺序、分节、版头检测、处理模式和诊断。
    返回值是可变文档模型，作为识别、规范化和渲染之间的兼容数据契约。
    """

    paragraphs: List[ParagraphData] = field(default_factory=list)
    tables: list = field(default_factory=list)
    body_blocks: list = field(default_factory=list)
    filepath: str = ""
    has_cover: bool = False
    doc_mode: str = ""
    body_sectPr: object = None
    section_relationship_parts: Dict[str, object] = field(default_factory=dict)
    even_and_odd_headers: object = None
    letterhead_detection: object = None
    strict_preservation: bool = False
    processing_strategy: str = "normalize"
    recognition_mode: str = "authoritative"
    normalization_changes: list = field(default_factory=list)
    recognition_diagnostics: dict = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizationChange:
    """记录一次可审计的规范化建议或应用结果。

    传入数据是段落号、动作、前后摘要、原因、置信度和是否应用。
    返回值是不可变审计记录，用于 strict/smart/normalize 模式说明改动边界。
    """

    paragraph_index: int
    action: str
    before: str
    after: str
    reason_code: str
    confidence: float
    applied: bool
