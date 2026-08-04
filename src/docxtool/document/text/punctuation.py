"""Safe punctuation normalization for Chinese-context text."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


PUNCTUATION_MODES = {"off", "safe", "standard"}


@dataclass(frozen=True)
class ProtectedSpan:
    start: int
    end: int
    kind: str
    text: str


@dataclass(frozen=True)
class PunctuationReplacement:
    start: int
    end: int
    replacement: str
    rule: str
    original: str


@dataclass(frozen=True)
class PunctuationResult:
    text: str
    replacements: tuple[PunctuationReplacement, ...]
    protected_spans: tuple[ProtectedSpan, ...]


_URL_RE = re.compile(r"\b(?:https?://|ftp://|www\.)[^\s<>\"]+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)(?::\d{1,5})?\b"
)
_IPV6_RE = re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){2,}[0-9A-Fa-f:.]*(?:%\w+)?(?:/\d{1,3})?\b")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:\b[A-Z]:[\\/][^\s<>\"|?*]*|\\\\[^\\/\s]+\\[^\s]+)")
_UNIX_PATH_RE = re.compile(r"(?<!\w)/(?:[^\s/]+/)+[^\s/]*")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_STANDARD_RE = re.compile(
    r"\b(?:GB/T|YY/T|WS/T|ISO|IEC|IEEE|RFC|JIS|DIN|EN|ASTM|GB)"
    r"\s*[A-Za-z0-9./-]*(?:\s*[-:]\s*\d{2,4})?\b"
)
_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,}(?:[-_A-Za-z0-9]+)?\b")
_DOMAIN_RE = re.compile(
    r"\b(?:[A-Za-z0-9-]+\.)+"
    r"(?:com|org|net|edu|gov|cn|io|dev|test|local|top|site|info|biz|co|uk)"
    r"(?::\d{1,5})?(?:/[^\s]*)?\b",
    re.IGNORECASE,
)
_FILE_RE = re.compile(
    r"(?<!\w)[\w.-]+\."
    r"(?:docx?|xlsx?|pptx?|pdf|txt|md|py|js|mjs|ts|json|xml|html?|css|png|jpe?g|gif|zip|rar|7z|db|log|env)\b",
    re.IGNORECASE,
)
_ABBR_RE = re.compile(
    r"\b(?:[A-Za-z]\.){2,}|"
    r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc)\.|"
    r"\b(?:e\.g|i\.e)\.",
    re.IGNORECASE,
)
_DOT_RUN_RE = re.compile(r"\.{3,}")
_DASH_RUN_RE = re.compile(r"-{2,}")
_NUMBERING_MARKER_RE = re.compile(
    r"(?m)^\s*(?:附件\s*[:：]\s*)?\d{1,3}(?P<marker>[.．])(?=\s*\S)"
)
_DUPLICATE_NUMBERING_PUNCT_RE = re.compile(
    r"(?m)^\s*(?:附件\s*[:：]\s*)?\d{1,3}[.．](?P<extra>[.．。]+)(?=\s*\S)"
)


def _normalize_mode(mode: str) -> str:
    normalized = (mode or "safe").lower()
    if normalized not in PUNCTUATION_MODES:
        raise ValueError(f"unsupported punctuation mode: {mode!r}")
    return normalized


def _is_cjk(ch: str) -> bool:
    return (
        "\u3400" <= ch <= "\u4dbf"
        or "\u4e00" <= ch <= "\u9fff"
        or "\uf900" <= ch <= "\ufaff"
        or "\u3000" <= ch <= "\u303f"
        or "\uff00" <= ch <= "\uffef"
    )


def _has_cjk(text: str) -> bool:
    return any(_is_cjk(ch) for ch in text)


def _visible_before(text: str, index: int) -> str:
    for pos in range(index - 1, -1, -1):
        if text[pos] not in " \t\r\n)）]】\"”'":
            return text[pos]
    return ""


def _visible_after(text: str, index: int) -> str:
    for pos in range(index + 1, len(text)):
        if text[pos] not in " \t\r\n(（[【\"“'":
            return text[pos]
    return ""


def _has_cjk_context(text: str, start: int, end: int) -> bool:
    before = _visible_before(text, start)
    after = _visible_after(text, end - 1)
    return _is_cjk(before) or _is_cjk(after)


def _add_span(spans: list[ProtectedSpan], start: int, end: int, kind: str, text: str) -> None:
    if 0 <= start < end:
        spans.append(ProtectedSpan(start, end, kind, text[start:end]))


def find_protected_spans(text: str) -> tuple[ProtectedSpan, ...]:
    """Return spans where punctuation must not be normalized."""

    spans: list[ProtectedSpan] = []
    patterns: Iterable[tuple[str, re.Pattern[str]]] = (
        ("url", _URL_RE),
        ("email", _EMAIL_RE),
        ("windows_path", _WINDOWS_PATH_RE),
        ("unix_path", _UNIX_PATH_RE),
        ("ipv4", _IPV4_RE),
        ("ipv6", _IPV6_RE),
        ("time", _TIME_RE),
        ("standard_number", _STANDARD_RE),
        ("version_or_decimal", _VERSION_RE),
        ("domain", _DOMAIN_RE),
        ("file_extension", _FILE_RE),
        ("english_abbreviation", _ABBR_RE),
    )
    for kind, pattern in patterns:
        for match in pattern.finditer(text):
            _add_span(spans, match.start(), match.end(), kind, text)
    for match in _NUMBERING_MARKER_RE.finditer(text):
        _add_span(
            spans,
            match.start("marker"),
            match.end("marker"),
            "numbering_marker",
            text,
        )
    return tuple(sorted(spans, key=lambda span: (span.start, -(span.end - span.start), span.kind)))


def _protected_mask(text: str, spans: Iterable[ProtectedSpan]) -> list[bool]:
    mask = [False] * len(text)
    for span in spans:
        for index in range(span.start, min(span.end, len(mask))):
            mask[index] = True
    return mask


def _range_is_unprotected(mask: list[bool], start: int, end: int) -> bool:
    return not any(mask[start:end])


def plan_punctuation_replacements(text: str, mode: str = "safe") -> tuple[PunctuationReplacement, ...]:
    """Plan safe punctuation replacements without changing protected spans."""

    mode = _normalize_mode(mode)
    if mode == "off" or not text:
        return ()

    spans = find_protected_spans(text)
    protected = _protected_mask(text, spans)
    occupied = [False] * len(text)
    replacements: list[PunctuationReplacement] = []

    def add(start: int, end: int, replacement: str, rule: str) -> None:
        if start >= end or not _range_is_unprotected(protected, start, end):
            return
        if any(occupied[start:end]):
            return
        if text[start:end] == replacement:
            return
        replacements.append(PunctuationReplacement(start, end, replacement, rule, text[start:end]))
        for index in range(start, end):
            occupied[index] = True

    for match in _DUPLICATE_NUMBERING_PUNCT_RE.finditer(text):
        add(match.start("extra"), match.end("extra"), "", "duplicate_numbering_punctuation")

    for match in _DOT_RUN_RE.finditer(text):
        if _has_cjk_context(text, match.start(), match.end()):
            add(match.start(), match.end(), "……", "ellipsis")

    for match in _DASH_RUN_RE.finditer(text):
        if _has_cjk_context(text, match.start(), match.end()):
            add(match.start(), match.end(), "——", "em_dash")

    quote_positions = [i for i, ch in enumerate(text) if ch == '"' and not protected[i]]
    while len(quote_positions) >= 2:
        start = quote_positions.pop(0)
        end = quote_positions.pop(0)
        inner = text[start + 1 : end]
        if "\n" not in inner and "\r" not in inner and 0 < len(inner) <= 120 and _has_cjk(inner):
            add(start, start + 1, "“", "double_quote_open")
            add(end, end + 1, "”", "double_quote_close")

    stack: list[int] = []
    for index, ch in enumerate(text):
        if protected[index] or occupied[index]:
            continue
        if ch == "(":
            stack.append(index)
        elif ch == ")" and stack:
            start = stack.pop()
            inner = text[start + 1 : index]
            if "\n" not in inner and "\r" not in inner and 0 < len(inner) <= 80 and _has_cjk(inner):
                add(start, start + 1, "（", "paren_open")
                add(index, index + 1, "）", "paren_close")

    simple_map = {
        ",": "，",
        ".": "。",
        ":": "：",
        ";": "；",
        "?": "？",
        "!": "！",
    }
    for index, ch in enumerate(text):
        if protected[index] or occupied[index] or ch not in simple_map:
            continue
        if _has_cjk_context(text, index, index + 1):
            add(index, index + 1, simple_map[ch], f"halfwidth_{ch}")

    return tuple(sorted(replacements, key=lambda replacement: replacement.start))


def apply_punctuation_replacements(text: str, replacements: Iterable[PunctuationReplacement]) -> str:
    by_start = {replacement.start: replacement for replacement in replacements}
    result: list[str] = []
    index = 0
    while index < len(text):
        replacement = by_start.get(index)
        if replacement is not None:
            result.append(replacement.replacement)
            index = replacement.end
        else:
            result.append(text[index])
            index += 1
    return "".join(result)


def normalize_punctuation(text: str, mode: str = "safe") -> PunctuationResult:
    """Normalize Chinese-context punctuation and report applied changes."""

    replacements = plan_punctuation_replacements(text, mode=mode)
    return PunctuationResult(
        text=apply_punctuation_replacements(text, replacements),
        replacements=replacements,
        protected_spans=find_protected_spans(text),
    )


def normalize_punctuation_text(text: str, mode: str = "safe") -> str:
    """Return normalized text only. Spaces and straight single quotes are unchanged."""

    return normalize_punctuation(text, mode=mode).text
