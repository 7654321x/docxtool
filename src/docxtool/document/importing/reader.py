"""DOCX 物理读取与 body 块提取。

本模块只读取 python-docx 与 OOXML 的物理事实：打开经关系修复的文件、
保留 body XML 顺序、收集表格/图片/分节以及保护紧邻对象的题注。它不参与
逻辑拆段、候选生成、状态机、规范化或最终段落类型裁决。
"""

from __future__ import annotations

import copy
import os
from typing import Callable, List

from docxtool.document.importing.images import (
    is_object_caption,
    is_standalone_image_paragraph,
)
from docxtool.document.importing.inline_tokens import extract_inline_tokens
from docxtool.document.importing.sections import (
    collect_section_header_footer_parts,
    extract_paragraph_sectPr,
)
from docxtool.document.models import DocumentData, ParagraphFeatures


def open_docx_document(
    filepath: str,
    *,
    document_factory: Callable[[str], object],
    repair_broken_rels_func: Callable[[str], str],
    import_error_type: type,
    cleanup_warning: Callable[[str], None],
):
    """打开一次 DOCX，并在打开后清理本次关系修复副本。

    传入原始文件路径、DOCX 构造器、关系修复函数、旧异常类型和告警回调。
    返回已打开的 python-docx 文档对象。修复副本的创建、异常形状和清理时机
    与旧 ``DocxImporter.load()`` 保持一致，调用方仍持有可 monkeypatch 的
    ``repair_broken_rels_func`` 边界。
    """
    repaired_filepath = repair_broken_rels_func(filepath)
    try:
        return document_factory(repaired_filepath)
    except Exception as exc:
        raise import_error_type(f"无法打开文件: {type(exc).__name__}") from exc
    finally:
        if repaired_filepath != filepath:
            try:
                os.unlink(repaired_filepath)
            except OSError:
                cleanup_warning("[修复] 临时 DOCX 清理失败")


def read_body_blocks(
    document,
    data: DocumentData,
    *,
    strict_preservation: bool,
    protected_letterhead_indexes: set[int],
    extract_features_func: Callable[[object, int], ParagraphFeatures],
) -> List[tuple]:
    """按 source body XML 顺序读取可供后续拆段的物理块。

    传入已打开的 DOCX、承载物理分节/表格事实的 ``DocumentData``、处理模式、
    版头保护索引和既有特征提取回调。返回值沿用旧 importer 的 tuple 布局，
    所以调用方后续的逻辑拆段和识别循环不需要改变任何判断或顺序。
    """
    from docx.oxml.ns import qn
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    data.even_and_odd_headers = copy.deepcopy(
        document.settings._element.find(qn("w:evenAndOddHeaders"))
    )

    raw_blocks: List[tuple] = []
    paragraph_index = 0
    body_index = 0
    for child in document._body._element.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = DocxParagraph(child, document._body)
            paragraph_features = extract_features_func(paragraph, paragraph_index)
            inline_tokens = extract_inline_tokens(paragraph)
            sect_pr = extract_paragraph_sectPr(paragraph)
            collect_section_header_footer_parts(document, sect_pr, data)
            paragraph_index += 1
            if body_index in protected_letterhead_indexes:
                raw_blocks.append(("letterhead_paragraph_xml", paragraph))
            elif paragraph_features.contains_image:
                raw_blocks.append(("paragraph_xml", paragraph))
            elif (
                strict_preservation
                or paragraph.text.strip()
                or sect_pr is not None
                or any(token.kind == "page_break" for token in inline_tokens)
            ):
                raw_blocks.append(
                    ("paragraph", paragraph, paragraph_features, inline_tokens, sect_pr)
                )
        elif child.tag == qn("w:tbl"):
            table = DocxTable(child, document._body)
            raw_blocks.append(("table", table))
            data.tables.append(table)
        elif child.tag == qn("w:sectPr"):
            data.body_sectPr = copy.deepcopy(child)
            collect_section_header_footer_parts(document, child, data)
            continue
        body_index += 1

    # 题注保护只覆盖紧邻表格或纯图片的第一行，不能让题注继续充当下一行锚点。
    for block_index in range(1, len(raw_blocks)):
        block = raw_blocks[block_index]
        previous = raw_blocks[block_index - 1]
        previous_is_caption_anchor = (
            previous[0] == "table"
            or (
                previous[0] == "paragraph_xml"
                and is_standalone_image_paragraph(previous[1])
            )
        )
        if (
            block[0] == "paragraph"
            and previous_is_caption_anchor
            and is_object_caption(block[1])
        ):
            raw_blocks[block_index] = (
                "protected_paragraph_xml",
                block[1],
                block[2],
            )

    return raw_blocks
