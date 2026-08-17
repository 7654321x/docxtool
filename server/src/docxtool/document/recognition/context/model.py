"""Document-wide recognition context data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HeadingFamily:
    level: int
    positions: tuple[int, ...]
    supported_positions: tuple[int, ...]
    parent_scope: tuple[int, ...] = ()
    source_family: str = ""

    @property
    def count(self) -> int:
        return len(self.positions)


@dataclass(frozen=True)
class DocumentContext:
    """Document-wide, index-addressable recognition evidence."""

    front_positions: tuple[int, ...]
    title_scores: tuple[float, ...]
    title_evidence: tuple[tuple[str, ...], ...]
    body_start: int | None
    body_start_reason: str
    front_scan_reason: str
    front_soft_threshold_exceeded: bool
    front_scan_soft_threshold: int
    heading_families: tuple[HeadingFamily, ...]
    heading_evidence: tuple[tuple[str, ...], ...]
    front_metadata_kinds: tuple[str | None, ...]
    attachment_note_evidence: tuple[tuple[str, ...], ...]
    attachment_item_evidence: tuple[tuple[str, ...], ...]
    signature_date_evidence: tuple[tuple[str, ...], ...]
    signature_org_evidence: tuple[tuple[str, ...], ...]

    def title_score(self, position: int) -> float:
        return self.title_scores[position] if 0 <= position < len(self.title_scores) else 0.0

    def title_reasons(self, position: int) -> tuple[str, ...]:
        return self.title_evidence[position] if 0 <= position < len(self.title_evidence) else ()

    def before_body(self, position: int) -> bool:
        return self.body_start is None or position < self.body_start

    def heading_family(self, position: int) -> HeadingFamily | None:
        for family in self.heading_families:
            if position in family.positions:
                return family
        return None

    def heading_reasons(self, position: int) -> tuple[str, ...]:
        return self.heading_evidence[position] if 0 <= position < len(self.heading_evidence) else ()

    def front_metadata_kind(self, position: int) -> str | None:
        return self.front_metadata_kinds[position] if 0 <= position < len(self.front_metadata_kinds) else None

    def attachment_note_reasons(self, position: int) -> tuple[str, ...]:
        return self.attachment_note_evidence[position] if 0 <= position < len(self.attachment_note_evidence) else ()

    def attachment_item_reasons(self, position: int) -> tuple[str, ...]:
        return self.attachment_item_evidence[position] if 0 <= position < len(self.attachment_item_evidence) else ()

    def signature_date_reasons(self, position: int) -> tuple[str, ...]:
        return self.signature_date_evidence[position] if 0 <= position < len(self.signature_date_evidence) else ()

    def signature_org_reasons(self, position: int) -> tuple[str, ...]:
        return self.signature_org_evidence[position] if 0 <= position < len(self.signature_org_evidence) else ()

    def diagnostic_summary(self) -> dict:
        return {
            "front_matter_positions": list(self.front_positions),
            "body_start": self.body_start,
            "body_start_reason": self.body_start_reason,
            "front_scan_reason": self.front_scan_reason,
            "front_soft_threshold_exceeded": self.front_soft_threshold_exceeded,
            "front_scan_soft_threshold": self.front_scan_soft_threshold,
            "heading_families": [
                _family_diagnostic(family)
                for family in self.heading_families
            ],
            "attachment_notes": [
                {"position": position, "evidence": list(evidence)}
                for position, evidence in enumerate(self.attachment_note_evidence)
                if evidence
            ],
            "attachment_note_items": [
                {"position": position, "evidence": list(evidence)}
                for position, evidence in enumerate(self.attachment_item_evidence)
                if evidence
            ],
            "signature_orgs": [
                {"position": position, "evidence": list(evidence)}
                for position, evidence in enumerate(self.signature_org_evidence)
                if evidence
            ],
            "signature_dates": [
                {"position": position, "evidence": list(evidence)}
                for position, evidence in enumerate(self.signature_date_evidence)
                if evidence
            ],
            "front_metadata": [
                {"position": position, "kind": kind}
                for position, kind in enumerate(self.front_metadata_kinds)
                if kind
            ],
        }


def _family_diagnostic(family: HeadingFamily) -> dict:
    result = {
        "level": family.level,
        "count": family.count,
        "positions": list(family.positions),
        "supported_count": len(family.supported_positions),
    }
    if family.parent_scope:
        result["parent_scope"] = list(family.parent_scope)
    if family.source_family:
        result["source_family"] = family.source_family
    return result
