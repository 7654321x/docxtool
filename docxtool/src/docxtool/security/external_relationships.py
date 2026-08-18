"""Pure policy helpers for external OOXML relationships."""

from __future__ import annotations

from urllib.parse import urlsplit


HYPERLINK_RELATIONSHIP_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)
ALLOWED_EXTERNAL_SCHEMES = frozenset({"http", "https", "mailto"})


def external_relationship_policy(rel_type: str, target: str) -> tuple[bool, str, str]:
    """Return ``allowed, reason_code, scheme`` without accessing the target."""
    value = str(target or "").strip()
    if value.startswith(("\\\\", "//")):
        return False, "EXTERNAL_UNC_TARGET", "unc"
    scheme = urlsplit(value).scheme.casefold()
    if rel_type != HYPERLINK_RELATIONSHIP_TYPE:
        return False, "EXTERNAL_RELATIONSHIP_TYPE_NOT_ALLOWED", scheme or "none"
    if scheme not in ALLOWED_EXTERNAL_SCHEMES:
        return False, "EXTERNAL_SCHEME_NOT_ALLOWED", scheme or "none"
    parsed = urlsplit(value)
    if scheme in {"http", "https"} and not parsed.netloc:
        return False, "EXTERNAL_TARGET_INVALID", scheme
    if scheme == "mailto" and not parsed.path:
        return False, "EXTERNAL_TARGET_INVALID", scheme
    return True, "ALLOWED_EXTERNAL_HYPERLINK", scheme


def sanitized_external_target(target: str) -> str:
    """Return a log-safe target without path, credentials, query, or fragment."""
    value = str(target or "").strip()
    if value.startswith(("\\\\", "//")):
        return "unc:[redacted]"
    parsed = urlsplit(value)
    scheme = parsed.scheme.casefold() or "none"
    if scheme == "mailto":
        return "mailto:[redacted]"
    host = parsed.hostname or ""
    return f"{scheme}://{host or '[redacted]'}"
