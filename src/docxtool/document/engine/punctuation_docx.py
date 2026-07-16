"""DOCX punctuation normalization that preserves run structure."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

from docxtool.document.engine.punctuation import PunctuationReplacement, plan_punctuation_replacements
from docxtool.security.docx_integrity import validate_docx_integrity


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS}
XML_SPACE = f"{{{XML_NS}}}space"


@dataclass(frozen=True)
class PunctuationScope:
    body: bool = True
    tables: bool = False
    headers: bool = False
    footers: bool = False


@dataclass(frozen=True)
class DocxPunctuationReport:
    input_path: Path
    output_path: Path
    changed_parts: int
    changed_paragraphs: int
    replacements: int
    integrity_ok: bool


_UNSAFE_TEXT_ANCESTORS = {
    f"{{{W_NS}}}hyperlink",
    f"{{{W_NS}}}drawing",
    f"{{{W_NS}}}pict",
    f"{{{W_NS}}}object",
    f"{{{W_NS}}}txbxContent",
}


def _scope_from_options(options: dict[str, Any] | None, scope: Any | None) -> PunctuationScope:
    if isinstance(scope, PunctuationScope):
        base = scope
    elif isinstance(scope, dict):
        base = PunctuationScope(
            body=bool(scope.get("body", True)),
            tables=bool(scope.get("tables", scope.get("table", False))),
            headers=bool(scope.get("headers", scope.get("header", False))),
            footers=bool(scope.get("footers", scope.get("footer", False))),
        )
    else:
        base = PunctuationScope()

    if not options:
        return base
    scope_options = options.get("scope")
    if isinstance(scope_options, PunctuationScope | dict):
        return _scope_from_options(None, scope_options)
    return PunctuationScope(
        body=bool(options.get("body", base.body)),
        tables=bool(options.get("tables", options.get("table", base.tables))),
        headers=bool(options.get("headers", options.get("header", base.headers))),
        footers=bool(options.get("footers", options.get("footer", base.footers))),
    )


def _part_is_selected(name: str, scope: PunctuationScope) -> bool:
    if name == "word/document.xml":
        return scope.body or scope.tables
    if name.startswith("word/header") and name.endswith(".xml"):
        return scope.headers
    if name.startswith("word/footer") and name.endswith(".xml"):
        return scope.footers
    return False


def _has_ancestor(element: etree._Element, tag: str) -> bool:
    return any(parent.tag == tag for parent in element.iterancestors())


def _is_text_node_safe(text_node: etree._Element) -> bool:
    if text_node.text is None:
        return False
    for parent in text_node.iterancestors():
        if parent.tag in _UNSAFE_TEXT_ANCESTORS:
            return False
    return True


def _paragraph_has_field(paragraph: etree._Element) -> bool:
    return bool(paragraph.xpath(".//w:fldChar | .//w:instrText | .//w:fldSimple", namespaces=NS))


def _iter_selected_paragraphs(root: etree._Element, part_name: str, scope: PunctuationScope):
    paragraphs = root.xpath(".//w:p", namespaces=NS)
    for paragraph in paragraphs:
        in_table = _has_ancestor(paragraph, f"{{{W_NS}}}tbl")
        if part_name == "word/document.xml":
            if in_table and not scope.tables:
                continue
            if not in_table and not scope.body:
                continue
        elif in_table and not scope.tables:
            continue
        if _paragraph_has_field(paragraph):
            continue
        yield paragraph


def _apply_replacements_to_nodes(
    text_nodes: list[etree._Element],
    replacements: tuple[PunctuationReplacement, ...],
) -> bool:
    if not replacements:
        return False

    by_start = {replacement.start: replacement for replacement in replacements}
    global_index = 0
    skip_until = 0
    changed = False

    for node in text_nodes:
        original = node.text or ""
        rebuilt: list[str] = []
        for ch in original:
            replacement = by_start.get(global_index)
            if replacement is not None:
                rebuilt.append(replacement.replacement)
                skip_until = replacement.end
                changed = True
            elif global_index >= skip_until:
                rebuilt.append(ch)
            else:
                changed = True
            global_index += 1
        updated = "".join(rebuilt)
        if updated != original:
            node.text = updated
            if updated[:1].isspace() or updated[-1:].isspace():
                node.set(XML_SPACE, "preserve")

    return changed


def _normalize_paragraph(paragraph: etree._Element, mode: str) -> int:
    safe_nodes = [node for node in paragraph.xpath(".//w:t", namespaces=NS) if _is_text_node_safe(node)]
    if not safe_nodes:
        return 0

    text = "".join(node.text or "" for node in safe_nodes)
    replacements = plan_punctuation_replacements(text, mode=mode)
    if not replacements:
        return 0
    _apply_replacements_to_nodes(safe_nodes, replacements)
    return len(replacements)


def _normalize_xml_part(data: bytes, part_name: str, mode: str, scope: PunctuationScope) -> tuple[bytes, int, int]:
    parser = etree.XMLParser(resolve_entities=False, remove_blank_text=False)
    root = etree.fromstring(data, parser=parser)
    changed_paragraphs = 0
    replacements = 0

    for paragraph in _iter_selected_paragraphs(root, part_name, scope):
        count = _normalize_paragraph(paragraph, mode)
        if count:
            changed_paragraphs += 1
            replacements += count

    if not replacements:
        return data, 0, 0
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=False), changed_paragraphs, replacements


def normalize_docx_punctuation(
    input_path: str | Path,
    output_path: str | Path,
    options: dict[str, Any] | None = None,
    scope: PunctuationScope | dict[str, Any] | None = None,
    mode: str = "safe",
) -> DocxPunctuationReport:
    """Normalize selected DOCX text nodes without rebuilding paragraphs or runs."""

    source = Path(input_path)
    target = Path(output_path)
    selected_scope = _scope_from_options(options, scope)
    if options and "mode" in options:
        mode = str(options["mode"])

    changed_parts = 0
    changed_paragraphs = 0
    replacements = 0

    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source, "r") as src, zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if _part_is_selected(item.filename, selected_scope):
                data, part_paragraphs, part_replacements = _normalize_xml_part(
                    data,
                    item.filename,
                    mode,
                    selected_scope,
                )
                if part_replacements:
                    changed_parts += 1
                    changed_paragraphs += part_paragraphs
                    replacements += part_replacements
            dst.writestr(item, data)

    report = validate_docx_integrity(target)
    return DocxPunctuationReport(
        input_path=source,
        output_path=target,
        changed_parts=changed_parts,
        changed_paragraphs=changed_paragraphs,
        replacements=replacements,
        integrity_ok=report.ok,
    )
