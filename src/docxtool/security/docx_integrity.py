"""Read-only OOXML integrity checks for generated DOCX packages."""

from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urldefrag, urlsplit
from xml.etree import ElementTree

PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

REQUIRED_PARTS = ("[Content_Types].xml", "_rels/.rels", "word/document.xml")
_XML_ENTITY_MARKERS = (b"<!doctype", b"<!entity")


@dataclass(frozen=True)
class IntegrityReport:
    """Summary of completed DOCX package integrity checks."""

    ok: bool
    part_count: int
    xml_part_count: int
    relationship_part_count: int
    relationship_count: int
    checked_part_count: int


class DocxIntegrityError(ValueError):
    """Stable validation error for malformed generated DOCX packages."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class _Relationship:
    source_rels: str
    rel_id: str
    target: str
    target_mode: str
    target_part: str | None


def validate_docx_integrity(path_or_bytes: str | bytes | bytearray | memoryview | Path | BinaryIO) -> IntegrityReport:
    """Validate generated DOCX package integrity without modifying the input."""

    try:
        with _open_zip(path_or_bytes) as archive:
            corrupted = archive.testzip()
            if corrupted:
                raise _error("CORRUPT_ZIP", f"ZIP member failed CRC check: {corrupted}")
            return _validate_archive(archive)
    except DocxIntegrityError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise _error("INVALID_ZIP", "Unable to open DOCX package as a valid ZIP archive") from None


def _open_zip(path_or_bytes: str | bytes | bytearray | memoryview | Path | BinaryIO) -> zipfile.ZipFile:
    if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
        return zipfile.ZipFile(io.BytesIO(bytes(path_or_bytes)), "r")
    return zipfile.ZipFile(path_or_bytes, "r")


def _validate_archive(archive: zipfile.ZipFile) -> IntegrityReport:
    members = _collect_members(archive)
    _require_parts(members)

    xml_roots = {
        name: _parse_xml_part(archive, name)
        for name in sorted(members)
        if _is_xml_part(name) or _is_relationship_part(name)
    }

    _validate_content_types(xml_roots["[Content_Types].xml"], members)
    relationships = _validate_relationship_parts(xml_roots, members)
    _validate_xml_relationship_references(xml_roots, relationships)
    checked_parts = _walk_reachable_parts(relationships)

    return IntegrityReport(
        ok=True,
        part_count=len(members),
        xml_part_count=sum(1 for name in members if _is_xml_part(name)),
        relationship_part_count=sum(1 for name in members if _is_relationship_part(name)),
        relationship_count=sum(len(rels) for rels in relationships.values()),
        checked_part_count=len(checked_parts),
    )


def _collect_members(archive: zipfile.ZipFile) -> set[str]:
    members: set[str] = set()
    for info in archive.infolist():
        name = info.filename
        if info.is_dir():
            _validate_package_part_name(name.rstrip("/"), allow_empty=True)
            continue
        _validate_package_part_name(name)
        if name in members:
            raise _error("DUPLICATE_PART", f"Duplicate package part: {name}")
        members.add(name)
    return members


def _validate_package_part_name(name: str, *, allow_empty: bool = False) -> None:
    if allow_empty and not name:
        return
    if not name or "\\" in name or name.startswith("/") or name.startswith("../") or "/../" in name:
        raise _error("INVALID_PART_NAME", f"Invalid package part name: {name or '<empty>'}")
    parsed = urlsplit(name)
    if parsed.scheme or parsed.netloc or posixpath.normpath(name) != name:
        raise _error("INVALID_PART_NAME", f"Invalid package part name: {name}")


def _require_parts(members: set[str]) -> None:
    missing = [name for name in REQUIRED_PARTS if name not in members]
    if missing:
        raise _error("MISSING_REQUIRED_PART", f"Missing required DOCX package part: {missing[0]}")


def _parse_xml_part(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    data = archive.read(name)
    lowered = data[:4096].lower()
    if any(marker in lowered for marker in _XML_ENTITY_MARKERS):
        raise _error("UNSAFE_XML", f"Unsafe XML declaration in package part: {name}")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise _error("BROKEN_XML", f"Broken XML in package part: {name}") from None


def _validate_content_types(content_types_root: ElementTree.Element, members: set[str]) -> None:
    if content_types_root.tag != f"{{{CONTENT_TYPES_NS}}}Types":
        raise _error("BROKEN_CONTENT_TYPES", "Invalid [Content_Types].xml root element")

    defaults: set[str] = set()
    overrides: set[str] = set()
    for child in content_types_root:
        if child.tag == f"{{{CONTENT_TYPES_NS}}}Default":
            extension = child.attrib.get("Extension", "").lower()
            content_type = child.attrib.get("ContentType", "")
            if extension and content_type:
                defaults.add(extension)
        elif child.tag == f"{{{CONTENT_TYPES_NS}}}Override":
            part_name = child.attrib.get("PartName", "")
            content_type = child.attrib.get("ContentType", "")
            if part_name.startswith("/") and content_type:
                overrides.add(part_name[1:])

    for part_name in sorted(members - {"[Content_Types].xml"}):
        extension = part_name.rsplit(".", 1)[-1].lower() if "." in part_name else ""
        if part_name not in overrides and extension not in defaults:
            raise _error("MISSING_CONTENT_TYPE", f"Missing content type coverage for package part: {part_name}")


def _validate_relationship_parts(
    xml_roots: dict[str, ElementTree.Element],
    members: set[str],
) -> dict[str, dict[str, _Relationship]]:
    relationships: dict[str, dict[str, _Relationship]] = {}
    for rels_name in sorted(name for name in members if _is_relationship_part(name)):
        source_part = _source_part_for_rels(rels_name)
        if source_part and source_part not in members:
            raise _error("DANGLING_RELS", f"Relationship part has no source package part: {rels_name}")

        root = xml_roots[rels_name]
        if root.tag != f"{{{PACKAGE_REL_NS}}}Relationships":
            raise _error("BROKEN_RELS", f"Invalid relationships root element in package part: {rels_name}")

        ids: dict[str, _Relationship] = {}
        for element in root:
            if element.tag != f"{{{PACKAGE_REL_NS}}}Relationship":
                continue
            rel_id = element.attrib.get("Id", "")
            target = element.attrib.get("Target", "")
            target_mode = element.attrib.get("TargetMode", "")
            if not rel_id or not target:
                raise _error("BROKEN_RELS", f"Relationship is missing Id or Target in package part: {rels_name}")
            if rel_id in ids:
                raise _error("DUPLICATE_REL_ID", f"Duplicate relationship Id {rel_id} in package part: {rels_name}")

            target_part = None
            if target_mode != "External":
                target_part = _resolve_internal_target(rels_name, target)
                if target_part not in members:
                    raise _error("MISSING_REL_TARGET", f"Relationship target is missing package part: {target_part}")

            ids[rel_id] = _Relationship(
                source_rels=rels_name,
                rel_id=rel_id,
                target=target,
                target_mode=target_mode,
                target_part=target_part,
            )
        relationships[rels_name] = ids
    return relationships


def _source_part_for_rels(rels_name: str) -> str | None:
    if rels_name == "_rels/.rels":
        return None
    marker = "/_rels/"
    if marker not in rels_name or not rels_name.endswith(".rels"):
        raise _error("BROKEN_RELS", f"Invalid relationship part location: {rels_name}")
    prefix, rels_file = rels_name.split(marker, 1)
    source_name = rels_file[:-5]
    if not prefix or not source_name:
        raise _error("BROKEN_RELS", f"Invalid relationship part location: {rels_name}")
    return f"{prefix}/{source_name}"


def _rels_name_for_source_part(part_name: str) -> str:
    directory, filename = posixpath.split(part_name)
    if directory:
        return f"{directory}/_rels/{filename}.rels"
    return f"_rels/{filename}.rels"


def _resolve_internal_target(rels_name: str, target: str) -> str:
    target_without_fragment = urldefrag(target)[0]
    parsed = urlsplit(target_without_fragment)
    if parsed.scheme or parsed.netloc or target_without_fragment.startswith(("/", "\\")):
        raise _error("REL_TARGET_ESCAPE", f"Relationship target escapes package boundary in package part: {rels_name}")
    if "\\" in target_without_fragment:
        raise _error("REL_TARGET_ESCAPE", f"Relationship target escapes package boundary in package part: {rels_name}")

    source_part = _source_part_for_rels(rels_name)
    base_dir = posixpath.dirname(source_part) if source_part else ""
    candidate = unquote(posixpath.normpath(posixpath.join(base_dir, target_without_fragment)))
    if candidate in ("", ".") or candidate.startswith("../") or "/../" in candidate or candidate.startswith("/"):
        raise _error("REL_TARGET_ESCAPE", f"Relationship target escapes package boundary in package part: {rels_name}")
    return candidate


def _validate_xml_relationship_references(
    xml_roots: dict[str, ElementTree.Element],
    relationships: dict[str, dict[str, _Relationship]],
) -> None:
    for part_name, root in sorted(xml_roots.items()):
        if part_name == "[Content_Types].xml" or _is_relationship_part(part_name):
            continue
        rel_ids = _referenced_relationship_ids(root)
        if not rel_ids:
            continue
        rels_name = _rels_name_for_source_part(part_name)
        available = relationships.get(rels_name, {})
        for rel_id in sorted(rel_ids):
            if rel_id not in available:
                raise _error("UNRESOLVED_XML_REL_ID", f"XML relationship reference {rel_id} is unresolved in package part: {part_name}")


def _referenced_relationship_ids(root: ElementTree.Element) -> set[str]:
    names = {f"{{{OFFICE_REL_NS}}}id", f"{{{OFFICE_REL_NS}}}embed", f"{{{OFFICE_REL_NS}}}link"}
    referenced: set[str] = set()
    for element in root.iter():
        for attr_name, attr_value in element.attrib.items():
            if attr_name in names and attr_value:
                referenced.add(attr_value)
    return referenced


def _walk_reachable_parts(relationships: dict[str, dict[str, _Relationship]]) -> set[str]:
    seen: set[str] = set()
    pending = [
        relationship.target_part
        for relationship in relationships.get("_rels/.rels", {}).values()
        if relationship.target_part
    ]
    while pending:
        part_name = pending.pop()
        if part_name in seen:
            continue
        seen.add(part_name)
        for relationship in relationships.get(_rels_name_for_source_part(part_name), {}).values():
            if relationship.target_part and relationship.target_part not in seen:
                pending.append(relationship.target_part)
    return seen


def _is_xml_part(name: str) -> bool:
    return name == "[Content_Types].xml" or name.endswith(".xml")


def _is_relationship_part(name: str) -> bool:
    return name == "_rels/.rels" or name.endswith(".rels")


def _error(code: str, message: str) -> DocxIntegrityError:
    return DocxIntegrityError(code, message)
