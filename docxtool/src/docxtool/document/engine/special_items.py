"""Render preserved non-text items in their original input order."""

from __future__ import annotations


def render_special_item(context, paragraph_data, *, compatibility_module) -> bool:
    doc = context.doc
    relationship_part_copier = context.relationship_part_copier
    referenced_style_copier = context.referenced_style_copier
    protected_paragraph_elements = context.protected_paragraph_elements
    if paragraph_data.type_id == "__table__":
        try:
            compatibility_module._copy_table(
                doc,
                paragraph_data.meta.get("table"),
                relationship_part_copier,
                referenced_style_copier,
            )
        except Exception as exc:
            raise compatibility_module.ExportError(
                f"表格完整复制失败，已中止导出: {exc}"
            ) from exc
        return True
    if paragraph_data.type_id == "__image__":
        try:
            protected_paragraph_elements.add(
                compatibility_module._copy_image(
                    doc,
                    paragraph_data.meta.get("image_xml"),
                    relationship_part_copier,
                )
            )
        except Exception as exc:
            raise compatibility_module.ExportError(
                f"图片完整复制失败，已中止导出: {exc}"
            ) from exc
        return True
    if paragraph_data.type_id == "__object_caption__":
        try:
            caption_element = compatibility_module._copy_preserved_paragraph(
                doc,
                paragraph_data.meta.get("paragraph_xml"),
                relationship_part_copier,
            )
            compatibility_module._set_object_caption_zero_spacing(caption_element)
            protected_paragraph_elements.add(caption_element)
        except Exception as exc:
            raise compatibility_module.ExportError(
                f"题注完整复制失败，已中止导出: {exc}"
            ) from exc
        return True
    if paragraph_data.type_id == "__letterhead__":
        if context.preserve_input_letterhead:
            try:
                protected_paragraph_elements.add(
                    compatibility_module._copy_preserved_paragraph(
                        doc,
                        paragraph_data.meta.get("paragraph_xml"),
                        relationship_part_copier,
                        referenced_style_copier,
                    )
                )
            except Exception as exc:
                raise compatibility_module.ExportError(
                    f"已有版头完整复制失败，已中止导出: {exc}"
                ) from exc
        return True
    if paragraph_data.type_id == "__preserved_source__":
        try:
            element = compatibility_module._copy_preserved_paragraph(
                doc,
                paragraph_data.meta.get("paragraph_xml"),
                relationship_part_copier,
                referenced_style_copier,
            )
            native_numbering = paragraph_data.meta.get("native_numbering")
            if native_numbering is not None:
                from docx.text.paragraph import Paragraph

                context.native_numbering_copier.apply(
                    Paragraph(element, doc._body), native_numbering
                )
                context.native_numbering_elements.add(element)
            protected_paragraph_elements.add(element)
        except Exception as exc:
            raise compatibility_module.ExportError(
                f"范围外段落完整复制失败，已中止导出: {exc}"
            ) from exc
        return True
    return False
