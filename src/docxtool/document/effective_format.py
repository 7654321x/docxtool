"""Resolve Word run formatting without mistaking inherited values for false.

``python-docx`` exposes direct properties conveniently, but a value of
``None`` means "not specified here", not "disabled".  Recognition needs the
effective value and its provenance so a logical fragment can safely use style
evidence without claiming that an unformatted run explicitly requested it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from docx.oxml.ns import qn
from lxml import etree


# Keep recognition policy in one place.  A partial run map is useful evidence,
# but it must not be presented to a host integration as a complete format map.
FORMAT_COVERAGE_CONFIRMED = 0.80

_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_FALSE_VALUES = frozenset(("0", "false", "off", "no", "none"))


@dataclass(frozen=True)
class EffectiveRunFormat:
    """Effective properties and where Word supplied each value.

    Boolean values are deliberately three-state: ``None`` means unknown,
    while ``False`` means an effective false value was explicitly found in a
    direct property or inherited style/default chain.
    """

    east_asia_font_name: Optional[str]
    ascii_font_name: Optional[str]
    font_size_pt: Optional[float]
    bold: Optional[bool]
    italic: Optional[bool]
    underline: Optional[bool]
    character_style_name: str
    sources: Tuple[str, ...]
    explicit: bool
    inherited: bool
    known: bool
    warnings: Tuple[str, ...]


def _xml_child(element, name):
    return element.find(qn(name)) if element is not None else None


def _style_rpr(style):
    element = getattr(style, "element", None)
    return _xml_child(element, "w:rPr")


def _style_chain(style, first_source: str) -> Iterable[Tuple[str, object]]:
    """Yield a style then its ``basedOn`` ancestors without cycles."""
    seen = set()
    current = style
    source = first_source
    while current is not None:
        style_id = getattr(current, "style_id", None) or id(current)
        if style_id in seen:
            break
        seen.add(style_id)
        rpr = _style_rpr(current)
        if rpr is not None:
            yield source, rpr
        current = getattr(current, "base_style", None)
        source = "based_on"


def _doc_default_rpr(paragraph):
    styles = getattr(getattr(paragraph, "part", None), "styles", None)
    styles_element = getattr(styles, "element", None)
    defaults = _xml_child(styles_element, "w:docDefaults")
    default = _xml_child(defaults, "w:rPrDefault")
    return _xml_child(default, "w:rPr")


def _theme_fonts(paragraph) -> Dict[str, str]:
    """Return the usable typefaces declared by the package theme.

    A theme can legitimately leave East Asian typefaces empty.  In that case
    the resolver leaves the value unknown instead of guessing a system font.
    """
    package = getattr(getattr(paragraph, "part", None), "package", None)
    for part in getattr(package, "parts", ()):
        if not str(getattr(part, "partname", "")).endswith("/theme/theme1.xml"):
            continue
        try:
            root = etree.fromstring(part.blob)
            scheme = root.find(".//{%s}fontScheme" % _DRAWING_NS)
            if scheme is None:
                return {}
            values = {}
            for prefix, tag in (("major", "majorFont"), ("minor", "minorFont")):
                group = scheme.find("{%s}%s" % (_DRAWING_NS, tag))
                if group is None:
                    continue
                latin = group.find("{%s}latin" % _DRAWING_NS)
                east_asia = group.find("{%s}ea" % _DRAWING_NS)
                if latin is not None and latin.get("typeface"):
                    values[prefix + "HAnsi"] = latin.get("typeface")
                    values[prefix + "Ascii"] = latin.get("typeface")
                if east_asia is not None and east_asia.get("typeface"):
                    values[prefix + "EastAsia"] = east_asia.get("typeface")
            return values
        except (AttributeError, TypeError, etree.XMLSyntaxError):
            return {}
    return {}


def _font_value(rpr, names: Tuple[str, ...], theme_fonts: Dict[str, str]):
    fonts = _xml_child(rpr, "w:rFonts")
    if fonts is None:
        return None
    for name in names:
        value = fonts.get(qn("w:" + name))
        if value:
            return value
        themed = fonts.get(qn("w:" + name + "Theme"))
        if themed:
            return theme_fonts.get(themed)
    return None


def _size_value(rpr) -> Optional[float]:
    element = _xml_child(rpr, "w:sz")
    value = element.get(qn("w:val")) if element is not None else None
    try:
        return float(value) / 2.0 if value is not None else None
    except (TypeError, ValueError):
        return None


def _boolean_value(rpr, name: str) -> Optional[bool]:
    element = _xml_child(rpr, "w:" + name)
    if element is None:
        return None
    value = (element.get(qn("w:val")) or "true").strip().lower()
    return value not in _FALSE_VALUES


def _direct_property_present(rpr, name: str) -> bool:
    return _xml_child(rpr, "w:" + name) is not None


def _first_value(candidates, getter):
    for source, rpr in candidates:
        value = getter(rpr)
        if value is not None:
            return value, source
    return None, ""


def resolve_effective_run_format(run, paragraph) -> EffectiveRunFormat:
    """Resolve effective text properties for a ``python-docx`` run.

    The function intentionally never mutates the document.  It is safe for
    the importer and SDK paths that need format evidence only.
    """
    direct_rpr = getattr(getattr(run, "_r", None), "rPr", None)
    candidates = []
    if direct_rpr is not None:
        candidates.append(("direct_run", direct_rpr))

    character_style = getattr(run, "style", None)
    character_style_name = str(getattr(character_style, "name", "") or "")
    candidates.extend(_style_chain(character_style, "character_style"))
    candidates.extend(_style_chain(getattr(paragraph, "style", None), "paragraph_style"))
    default_rpr = _doc_default_rpr(paragraph)
    if default_rpr is not None:
        candidates.append(("doc_defaults", default_rpr))

    theme_fonts = _theme_fonts(paragraph)
    east_asia, east_source = _first_value(
        candidates,
        lambda rpr: _font_value(rpr, ("eastAsia", "cs", "ascii", "hAnsi"), theme_fonts),
    )
    ascii_name, ascii_source = _first_value(
        candidates,
        lambda rpr: _font_value(rpr, ("ascii", "hAnsi", "cs", "eastAsia"), theme_fonts),
    )
    size, size_source = _first_value(candidates, _size_value)
    bold, bold_source = _first_value(candidates, lambda rpr: _boolean_value(rpr, "b"))
    italic, italic_source = _first_value(candidates, lambda rpr: _boolean_value(rpr, "i"))
    underline, underline_source = _first_value(candidates, lambda rpr: _boolean_value(rpr, "u"))

    explicit = bool(direct_rpr is not None and any((
        _direct_property_present(direct_rpr, "rFonts"),
        _direct_property_present(direct_rpr, "sz"),
        _direct_property_present(direct_rpr, "b"),
        _direct_property_present(direct_rpr, "i"),
        _direct_property_present(direct_rpr, "u"),
    )))
    property_sources = tuple(source for source in (
        east_source, ascii_source, size_source, bold_source, italic_source, underline_source,
    ) if source)
    inherited = bool(property_sources) and not explicit and any(
        source != "direct_run" for source in property_sources
    )
    warnings = []
    if not property_sources:
        warnings.append("FORMAT_UNKNOWN")
    elif not east_asia and not ascii_name:
        warnings.append("FONT_UNKNOWN")
    if any(source == "doc_defaults" for source in property_sources):
        warnings.append("FORMAT_INHERITED_FROM_DOC_DEFAULTS")
    return EffectiveRunFormat(
        east_asia_font_name=east_asia,
        ascii_font_name=ascii_name,
        font_size_pt=size,
        bold=bold,
        italic=italic,
        underline=underline,
        character_style_name=character_style_name,
        sources=tuple(dict.fromkeys(property_sources)),
        explicit=explicit,
        inherited=inherited,
        known=bool(property_sources),
        warnings=tuple(dict.fromkeys(warnings)),
    )
