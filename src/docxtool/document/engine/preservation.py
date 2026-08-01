"""源 OOXML 对象保留与关系迁移。

本模块属于 Renderer 内部能力：只负责把表格、图片、题注、已有版头和
页眉页脚关系安全复制到输出 DOCX，不识别段落类型，也不修改排版规则。
"""

from __future__ import annotations

import copy
import io
import re

from docx.opc.constants import CONTENT_TYPE as CT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.parts.hdrftr import FooterPart, HeaderPart

from docxtool.document.style_config import ExportError, logger
from docxtool.security.external_relationships import (
    external_relationship_policy,
    sanitized_external_target,
)


def external_relationship_record(rel) -> dict:
    """生成外部关系脱敏记录。

    传入 python-docx relationship 对象；返回可写入统计信息的 dict，
    不包含完整外链地址，用于提示被移除或保留的关系类型。
    """
    allowed, reason_code, scheme = external_relationship_policy(rel.reltype, rel.target_ref)
    return {
        "allowed": allowed,
        "relationship_type": rel.reltype.rsplit("/", 1)[-1],
        "sanitized_target": sanitized_external_target(rel.target_ref),
        "scheme": scheme,
        "reason_code": reason_code,
    }


def sanitize_relationship_xml(blob: bytes, relationships, removed: list[dict]) -> bytes:
    """移除部件 XML 中禁止外部关系的引用。

    传入源部件 XML bytes、该部件关系集合和移除记录列表；返回清理后的
    XML bytes，并把脱敏关系记录追加到 removed。
    """
    disallowed = {
        rel.rId: external_relationship_record(rel)
        for rel in relationships
        if rel.is_external and not external_relationship_policy(rel.reltype, rel.target_ref)[0]
    }
    if not disallowed:
        return blob
    try:
        from lxml import etree

        root = etree.fromstring(blob)
        for node in root.iter():
            for attribute, value in list(node.attrib.items()):
                if value not in disallowed:
                    continue
                node.attrib.pop(attribute, None)
                if disallowed[value] not in removed:
                    removed.append(disallowed[value])
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
    except (ValueError, TypeError) as exc:
        raise ExportError("无法安全移除外部 OOXML 关系引用") from exc


class SectionRelationshipCopier:
    """复制页眉页脚等部件及其关系树。

    构造时传入目标 package 和外部关系移除记录列表；copy_part 返回复制到
    目标包中的 Part，并递归复制其内部关系。
    """

    def __init__(self, package, removed_external_relationships=None):
        self._package = package
        self._removed_external_relationships = (
            removed_external_relationships
            if removed_external_relationships is not None
            else []
        )
        self._parts_by_source_id = {}
        self._used_partnames = {str(part.partname) for part in package.iter_parts()}

    def copy_part(self, source_part):
        """复制单个源部件。

        传入源 Part；返回目标包中的新 Part。重复传入同一源 Part 时返回
        已复制对象，避免一个页眉页脚被重复写入。
        """
        key = id(source_part)
        if key in self._parts_by_source_id:
            return self._parts_by_source_id[key]

        partname = self._next_partname(source_part)
        source_blob = sanitize_relationship_xml(
            source_part.blob,
            source_part.rels.values(),
            self._removed_external_relationships,
        )
        if source_part.content_type == CT.WML_HEADER:
            copied = HeaderPart.load(partname, source_part.content_type, source_blob, self._package)
        elif source_part.content_type == CT.WML_FOOTER:
            copied = FooterPart.load(partname, source_part.content_type, source_blob, self._package)
        else:
            copied = Part.load(partname, source_part.content_type, source_blob, self._package)

        self._parts_by_source_id[key] = copied

        for rel in source_part.rels.values():
            if rel.is_external:
                allowed, _reason, _scheme = external_relationship_policy(rel.reltype, rel.target_ref)
                if allowed:
                    copied.load_rel(rel.reltype, rel.target_ref, rel.rId, is_external=True)
            else:
                copied.load_rel(rel.reltype, self.copy_part(rel.target_part), rel.rId)

        return copied

    def _next_partname(self, source_part):
        """为复制部件分配唯一包路径。

        传入源 Part；返回目标包中尚未使用的 PackURI。
        """
        source_name = str(source_part.partname)
        if source_part.content_type == CT.WML_HEADER:
            pattern = "/word/header%d.xml"
        elif source_part.content_type == CT.WML_FOOTER:
            pattern = "/word/footer%d.xml"
        else:
            directory, filename = source_name.rsplit("/", 1)
            if "." in filename:
                stem, ext = filename.rsplit(".", 1)
                stem = re.sub(r"\d+$", "", stem) or stem
                pattern = f"{directory}/{stem}%d.{ext}"
            else:
                stem = re.sub(r"\d+$", "", filename) or filename
                pattern = f"{directory}/{stem}%d"

        for number in range(1, 10000):
            candidate = pattern % number
            if candidate not in self._used_partnames:
                self._used_partnames.add(candidate)
                return PackURI(candidate)
        raise ExportError(f"无法为复制的部件分配唯一名称: {source_name}")


class ReferencedStyleCopier:
    """复制透传对象实际引用的样式。

    构造时传入目标文档 styles XML；方法接收源对象 XML 和源 styles XML，
    返回值为空，直接把引用样式及依赖复制到目标 styles 中。
    """

    def __init__(self, target_styles_element):
        self._target = target_styles_element
        self._mapped = {}
        self._counter = 0

    def remap_element_styles(self, element, source_styles_element) -> None:
        """重映射元素中的样式引用。

        传入待复制元素和源 styles XML；返回 None，直接改写元素上的
        styleId，使其指向已复制到目标文档的隔离样式。
        """
        if source_styles_element is None:
            raise ExportError("源文档缺少样式定义，无法保留表格文字格式")
        for tag in ("w:tblStyle", "w:pStyle", "w:rStyle"):
            for reference in element.findall(".//" + qn(tag)):
                source_id = reference.get(qn("w:val"))
                if source_id:
                    reference.set(qn("w:val"), self._copy_style(source_styles_element, source_id))

    def preserve_table_default_paragraph_style(self, table_element, source_styles_element) -> None:
        """为表格单元格显式绑定源默认段落样式。

        传入表格 XML 和源 styles XML；返回 None。没有显式 pStyle 的单元格
        段落会写入隔离后的源默认样式，避免 WPS 回退到输出正文样式。
        """
        default_style = None
        for style in source_styles_element.findall(qn("w:style")):
            if (
                style.get(qn("w:type")) == "paragraph"
                and style.get(qn("w:default")) in {"1", "true", "on"}
            ):
                default_style = style
                break
        if default_style is None:
            raise ExportError("源文档缺少默认段落样式，无法保留表格文字格式")
        source_id = default_style.get(qn("w:styleId"))
        if not source_id:
            raise ExportError("源文档默认段落样式缺少 styleId")
        target_id = self._copy_style(source_styles_element, source_id)

        for paragraph in table_element.findall(".//" + qn("w:p")):
            p_pr = paragraph.find(qn("w:pPr"))
            if p_pr is None:
                p_pr = OxmlElement("w:pPr")
                paragraph.insert(0, p_pr)
            if p_pr.find(qn("w:pStyle")) is not None:
                continue
            p_style = OxmlElement("w:pStyle")
            p_style.set(qn("w:val"), target_id)
            p_pr.insert(0, p_style)

    def _copy_style(self, source_styles_element, source_id: str) -> str:
        """复制单个样式及依赖。

        传入源 styles XML 和源 styleId；返回目标文档中可引用的新 styleId。
        """
        key = (id(source_styles_element), source_id)
        if key in self._mapped:
            return self._mapped[key]

        source_style = source_styles_element.find(
            f".//{qn('w:style')}[@{qn('w:styleId')}='{source_id}']"
        )
        if source_style is None:
            raise ExportError(f"表格引用的源样式不存在: {source_id}")

        is_source_default = (
            source_style.get(qn("w:type")) == "paragraph"
            and source_style.get(qn("w:default")) in {"1", "true", "on"}
        )
        target_id = source_id
        existing = self._find_target(target_id)
        if is_source_default or existing is not None:
            target_id = self._next_id(source_id)
        self._mapped[key] = target_id

        copied = copy.deepcopy(source_style)
        copied.set(qn("w:styleId"), target_id)
        copied.attrib.pop(qn("w:default"), None)
        if is_source_default:
            # WPS 可能仍按最后一个 Normal 样式反算网格；隔离名称可避免污染。
            style_name = copied.find(qn("w:name"))
            if style_name is None:
                style_name = OxmlElement("w:name")
                copied.insert(0, style_name)
            style_name.set(qn("w:val"), f"Docxtool Preserved {source_id}")
        for dependency_tag in ("w:basedOn", "w:next", "w:link"):
            dependency = copied.find(qn(dependency_tag))
            if dependency is not None:
                dependency_id = dependency.get(qn("w:val"))
                if dependency_id:
                    dependency.set(
                        qn("w:val"), self._copy_style(source_styles_element, dependency_id)
                    )
        self._target.append(copied)
        return target_id

    def _find_target(self, style_id: str):
        """查找目标 styles 中是否已有 styleId。

        传入目标 styleId；返回匹配的 XML 元素或 None。
        """
        return self._target.find(
            f".//{qn('w:style')}[@{qn('w:styleId')}='{style_id}']"
        )

    def _next_id(self, source_id: str) -> str:
        """生成隔离后的样式 ID。

        传入源 styleId；返回目标 styles 中尚未存在的 DCT-Preserved-* ID。
        """
        safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", source_id).strip("-") or "Style"
        while True:
            self._counter += 1
            candidate = f"DCT-Preserved-{safe_id}-{self._counter}"
            if self._find_target(candidate) is None:
                return candidate


def copy_table(doc, table, part_copier, style_copier) -> None:
    """原样复制表格和其引用资源。

    传入目标 Document、源 table、关系复制器和样式复制器；返回 None，
    直接把表格 XML 追加到输出正文，并迁移所有关系。
    """
    if table is None:
        raise ExportError("缺少源表格对象，无法保证表格完整复制")
    tbl_element = copy.deepcopy(table._tbl)
    style_copier.remap_element_styles(tbl_element, table.part.styles.element)
    style_copier.preserve_table_default_paragraph_style(
        tbl_element, table.part.styles.element
    )
    remap_element_relationships(tbl_element, table.part, doc.part, part_copier)
    append_body_element(doc, tbl_element)


def remap_element_relationships(element, source_part, target_part, part_copier) -> None:
    """迁移 XML 元素内部引用的关系 ID。

    传入已复制 XML、源 Part、目标 Part 和关系复制器；返回 None。无法解析
    或迁移的内部关系会抛出 ExportError，禁止生成缺资源 DOCX。
    """
    remapped = {}
    source_rels = source_part.rels

    for node in element.iter():
        for attr_name, old_rid in list(node.attrib.items()):
            if old_rid not in source_rels:
                continue
            if old_rid not in remapped:
                rel = source_rels[old_rid]
                if rel.is_external:
                    allowed, _reason, _scheme = external_relationship_policy(rel.reltype, rel.target_ref)
                    if not allowed:
                        node.attrib.pop(attr_name, None)
                        if part_copier is not None:
                            record = external_relationship_record(rel)
                            if record not in part_copier._removed_external_relationships:
                                part_copier._removed_external_relationships.append(record)
                        continue
                    new_rid = target_part.relate_to(rel.target_ref, rel.reltype, is_external=True)
                else:
                    if part_copier is None:
                        raise ExportError(f"缺少关系部件复制器，无法复制表格关系: {old_rid}")
                    copied_part = part_copier.copy_part(rel.target_part)
                    new_rid = target_part.relate_to(copied_part, rel.reltype)
                remapped[old_rid] = new_rid
            node.set(attr_name, remapped[old_rid])

    unresolved = {
        value
        for node in element.iter()
        for value in node.attrib.values()
        if isinstance(value, str) and value.startswith("rId") and value not in target_part.rels
    }
    if unresolved:
        raise ExportError(f"表格包含无法迁移的关系引用: {', '.join(sorted(unresolved))}")


def append_body_element(doc, element) -> None:
    """把原始 XML 插入文档正文。

    传入目标 Document 和 body 子元素；返回 None。元素会插入到 sectPr 前，
    保持 Word body XML 顺序合法。
    """
    body = doc.element.body
    sectPr = body.sectPr
    if sectPr is not None:
        sectPr.addprevious(element)
    else:
        body.append(element)


def remap_image_relationships(element, source_part, target_part) -> None:
    """复制图片 XML 中引用的图片二进制关系。

    传入图片段落/table XML、源 Part 和目标 Part；返回 None，直接把 blip
    或 VML 图片关系改写为目标文档的新 rId。
    """
    for blip in element.findall(".//" + qn("a:blip")):
        for attr in (qn("r:embed"), qn("r:link")):
            old_rid = blip.get(attr)
            if not old_rid:
                continue
            related = source_part.related_parts.get(old_rid)
            if related is None or not hasattr(related, "blob"):
                continue
            new_rid, _ = target_part.get_or_add_image(io.BytesIO(related.blob))
            blip.set(attr, new_rid)

    try:
        legacy_images = element.findall(".//" + qn("v:imagedata"))
    except KeyError:
        legacy_images = []
    for imagedata in legacy_images:
        old_rid = imagedata.get(qn("r:id"))
        if not old_rid:
            continue
        related = source_part.related_parts.get(old_rid)
        if related is None or not hasattr(related, "blob"):
            continue
        new_rid, _ = target_part.get_or_add_image(io.BytesIO(related.blob))
        imagedata.set(qn("r:id"), new_rid)


def copy_preserved_paragraph(doc, source_para, part_copier, style_copier=None):
    """原样复制受保护段落。

    传入目标 Document、源段落、关系复制器和可选样式复制器；返回复制后的
    XML 元素。用于图片、题注、已有版头等不应重排版的对象。
    """
    if source_para is None:
        raise ExportError("缺少源段落对象，无法保证对象完整复制")
    p_element = copy.deepcopy(source_para._p)
    remap_element_relationships(p_element, source_para.part, doc.part, part_copier)
    if style_copier is not None:
        style_copier.remap_element_styles(p_element, source_para.part.styles.element)
    append_body_element(doc, p_element)
    return p_element


def set_object_caption_zero_spacing(paragraph_element) -> None:
    """仅归一化题注段落间距。

    传入已复制的题注段落 XML；返回 None。只把段前段后设为 0，其他
    字体、字号、对齐和题注文字保持源文档不变。
    """
    p_pr = paragraph_element.find(qn("w:pPr"))
    if p_pr is None:
        p_pr = OxmlElement("w:pPr")
        paragraph_element.insert(0, p_pr)
    spacing = p_pr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        p_pr.append(spacing)
    for attr in ("w:before", "w:after", "w:beforeLines", "w:afterLines"):
        spacing.set(qn(attr), "0")
    for attr in ("w:beforeAutospacing", "w:afterAutospacing"):
        spacing.attrib.pop(qn(attr), None)


def copy_image(doc, source_para, part_copier, style_copier=None):
    """原样复制图片段落。

    传入目标 Document、源图片段落和关系/样式复制器；返回复制后的 XML
    元素。该函数只做资源保留，不修改图片尺寸或题注。
    """
    element = copy_preserved_paragraph(doc, source_para, part_copier, style_copier)
    logger.debug("[引擎] 图片段落已原样复制 chars=%s", len(source_para.text))
    return element
