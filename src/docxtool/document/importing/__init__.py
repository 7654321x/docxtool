"""DOCX 物理导入层辅助包。"""
"""Physical DOCX importing helpers."""

from docxtool.document.importing.features import extract_paragraph_features
from docxtool.document.importing.numbering import is_auto_numbered_item
from docxtool.document.importing.relationships import repair_broken_rels

__all__ = ["extract_paragraph_features", "is_auto_numbered_item", "repair_broken_rels"]
