"""OOXML relationship repair helpers used while importing DOCX files."""

from __future__ import annotations

import os
import tempfile
import zipfile
from xml.etree import ElementTree as ET

from docxtool.document.diagnostics.logging import logger


def _remove_null_relationships(data: bytes) -> tuple[bytes, bool]:
    """删除 document.xml.rels 中指向 ../NULL 的关系。

    传入数据是 `word/_rels/document.xml.rels` 的 XML bytes。返回值是
    可能被改写后的 XML bytes，以及是否实际删除了关系。该函数只处理
    OOXML 关系节点，不读取或修改 DOCX 其他内容。
    """
    root = ET.fromstring(data)
    removed = False
    for relationship in list(root):
        target = (relationship.get("Target") or "").replace("\\", "/")
        if target == "../NULL":
            root.remove(relationship)
            removed = True
    if not removed:
        return data, False
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), True


def repair_broken_rels(filepath: str) -> str:
    """为导入阶段修复 DOCX 中损坏的关系引用。

    传入数据是原始 `.docx` 文件路径。若发现 `Target="../NULL"`，返回
    位于同目录的临时修复副本路径；若无需修复或修复失败，返回原路径。
    调用方负责在成功打开临时副本后删除该临时文件。
    """
    need_fix = False
    try:
        with zipfile.ZipFile(filepath, "r") as archive:
            rels_items = [
                item for item in archive.infolist()
                if item.filename.replace("\\", "/") == "word/_rels/document.xml.rels"
            ]
            if len(rels_items) == 1:
                _, need_fix = _remove_null_relationships(archive.read(rels_items[0]))
    except Exception:
        return filepath

    if not need_fix:
        return filepath

    logger.info("[修复] 检测到损坏引用 Target=\"../NULL\"，自动修复…")
    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".docx",
        dir=os.path.dirname(os.path.abspath(filepath)),
    )
    tmp.close()

    try:
        with zipfile.ZipFile(filepath, "r") as input_archive:
            with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as output_archive:
                for item in input_archive.infolist():
                    data = input_archive.read(item)
                    if item.filename == "word/_rels/document.xml.rels":
                        data, _ = _remove_null_relationships(data)
                    output_archive.writestr(item, data)
        logger.info("[修复] 损坏关系已写入任务临时副本")
        return tmp.name
    except Exception as exc:
        try:
            os.unlink(tmp.name)
        except OSError:
            logger.warning("[修复] 临时文件清理失败")
        logger.warning("[修复] 失败: %s", type(exc).__name__)
        return filepath
