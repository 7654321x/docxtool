"""Paragraph physical feature extraction for DOCX importing."""

from __future__ import annotations

from docxtool.document.importing.images import contains_visible_image
from docxtool.document.importing import numbering as numbering_module
from docxtool.document.importing import physical_format as physical_format_module
from docxtool.document.models import ParagraphFeatures
from docxtool.document.segmentation import source_locator as source_locator_module
from docxtool.document.diagnostics.logging import logger


def extract_paragraph_features(paragraph, index: int, *, detect_numbering_prefix_func) -> ParagraphFeatures:
    """从 python-docx 段落读取物理格式特征。

    传入数据是 `python-docx` 的 Paragraph、物理段落序号和编号前缀检测函数。
    返回值是 `ParagraphFeatures`，包含源文本 locator、run 字体字号、加粗比例、
    对齐、缩进、图片和 Word 自动编号事实；本函数只读取物理事实，不判断最终类型。
    """
    text = paragraph.text.strip()
    features = source_locator_module.build_physical_source_features(paragraph.text, index)

    if paragraph.style:
        features.style_name = paragraph.style.name or ""

    physical_format_module.apply_physical_format_features(paragraph, features)

    features.numbering_prefix = detect_numbering_prefix_func(text)
    features.contains_image = contains_visible_image(paragraph._element)
    numbering_module.apply_physical_numbering_features(
        features,
        paragraph,
        text,
        debug_logger=logger,
    )

    return features
