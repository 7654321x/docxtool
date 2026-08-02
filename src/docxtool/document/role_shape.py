"""Shared structural evidence for front-matter role and person lines."""

from __future__ import annotations

import re


ROLE_HINT_RE = re.compile(
    r"(?:书记|主任|主席|部长|局长|处长|科长|司长|厅长|市长|县长|区长|"
    r"镇长|乡长|院长|校长|政委|组长|队长|秘书长|委员|常委|负责人|"
    r"经理|总监|工程师|专员|督导员|顾问|总会计师|总经济师|同志|代表)"
)
PERSON_NAME_RE = re.compile(r"[\u4e00-\u9fff·×X]{2,4}$")
NON_PERSON_SUFFIX_RE = re.compile(
    r"(?:报告|总结|方案|计划|意见|通知|办法|材料|讲话|发言|纪要|决定|"
    r"决议|规定|制度|会议|工作)$"
)


def has_role_hint(text: str) -> bool:
    """Return whether text contains a generic personal role expression."""
    return bool(ROLE_HINT_RE.search(re.sub(r"\s+", "", text or "")))


def is_person_name_suffix(text: str) -> bool:
    """Return whether a short suffix is name-shaped rather than document-shaped."""
    value = re.sub(r"\s+", "", text or "")
    return bool(PERSON_NAME_RE.fullmatch(value) and not NON_PERSON_SUFFIX_RE.search(value))


def has_compact_role_name_shape(text: str) -> bool:
    """Return whether a role is immediately followed by a name-shaped suffix."""
    compact = re.sub(r"\s+", "", text or "")
    return any(
        is_person_name_suffix(compact[match.end():])
        for match in ROLE_HINT_RE.finditer(compact)
    )
