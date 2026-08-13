"""Host-neutral verification of a recognition plan against local text."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Optional, Sequence, Tuple

from .constants import (
    HOST_TEXT_CONTRACT_VERSION as SDK_HOST_TEXT_CONTRACT_VERSION,
    OFFSET_ENCODING,
    SOURCE_LOCATOR_VERSION as SDK_SOURCE_LOCATOR_VERSION,
)
from docxtool.document.source_tape import (
    HOST_TEXT_CONTRACT_VERSION,
    SOURCE_LOCATOR_VERSION,
    SourceTape,
    canonicalize_text,
)
from .errors import BindingError, InvalidHostSnapshotError, InvalidRecognitionPlanError, UnsupportedContractError

from .models import (
    BoundRecognitionBlock,
    HostParagraph,
    HostSnapshot,
    HostSnapshotSummary,
    PhysicalParagraphBinding,
    RecognitionBinding,
    RecognitionBlock,
    RecognitionPlan,
)
from .validation import (
    host_snapshot_from_dict,
    recognition_plan_from_dict,
    validate_host_snapshot,
    validate_recognition_plan,
)


def _raise_plan_report(report) -> None:
    if report.valid:
        return
    first = report.errors[0]
    raise InvalidRecognitionPlanError(
        "SDK 协议校验失败: {0}".format(first.path),
        code=first.code,
        details=first.detail,
    )


def _raise_snapshot_report(report) -> None:
    if report.valid:
        return
    first = report.errors[0]
    raise InvalidHostSnapshotError(
        "SDK 协议校验失败: {0}".format(first.path),
        code=first.code,
        details=first.detail,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _recommended_action(status: str) -> str:
    if status == "confirmed":
        return "verify_host_range"
    if status == "review":
        return "preview_only"
    return "skip"


def _raw_index_for_utf16_offset(value: str, offset: Optional[int]) -> Optional[int]:
    """Return a code-point boundary for an exact UTF-16 offset."""
    if offset is None or offset < 0:
        return None
    current = 0
    if offset == 0:
        return 0
    for index, character in enumerate(value or "", start=1):
        current += 2 if ord(character) > 0xFFFF else 1
        if current == offset:
            return index
        if current > offset:
            return None
    return len(value or "") if current == offset else None


@dataclass(frozen=True)
class _HostText:
    paragraph: HostParagraph
    tape: SourceTape
    raw_hash: str
    canonical_hash: str


@dataclass(frozen=True)
class _PhysicalGroup:
    physical_index: int
    raw_hash: str
    canonical_hash: str
    blocks: Tuple[RecognitionBlock, ...]


def _coerce_snapshot(value: HostSnapshot | Mapping[str, Any]) -> HostSnapshot:
    if isinstance(value, HostSnapshot):
        _raise_snapshot_report(validate_host_snapshot(value))
        return value
    if isinstance(value, HostSnapshotSummary):
        raise BindingError(
            "HostSnapshotSummary 不能用于绑定",
            details={"path": "$", "object_kind": "HostSnapshotSummary"},
        )
    if isinstance(value, Mapping) and value.get("summary_type") == "host-snapshot-summary-v1":
        raise BindingError(
            "HostSnapshotSummary 不能用于绑定",
            details={"path": "$.summary_type", "object_kind": "HostSnapshotSummary"},
        )
    return host_snapshot_from_dict(value)


def _coerce_plan(value: RecognitionPlan | Mapping[str, Any]) -> RecognitionPlan:
    if isinstance(value, RecognitionPlan):
        _raise_plan_report(validate_recognition_plan(value))
        return value
    if isinstance(value, Mapping):
        return recognition_plan_from_dict(value)
    raise BindingError("plan 必须为 RecognitionPlan 或 JSON 对象")


def _validate_snapshot_contract(snapshot: HostSnapshot) -> None:
    if snapshot.text_contract_version != SDK_HOST_TEXT_CONTRACT_VERSION:
        raise UnsupportedContractError(
            "不支持的宿主文本契约",
            code="UNSUPPORTED_HOST_TEXT_CONTRACT",
            details={"path": "host_snapshot.text_contract_version"},
        )
    if snapshot.offset_encoding != OFFSET_ENCODING:
        raise UnsupportedContractError(
            "不支持的 offset encoding",
            code="UNSUPPORTED_OFFSET_ENCODING",
            details={"path": "host_snapshot.offset_encoding"},
        )


def _host_texts(snapshot: HostSnapshot) -> Tuple[_HostText, ...]:
    return tuple(
        _HostText(
            paragraph=item,
            tape=SourceTape.from_text(
                item.raw_text,
                contract_version=snapshot.text_contract_version,
            ),
            raw_hash=_sha256(item.raw_text),
            canonical_hash=_sha256(
                canonicalize_text(item.raw_text)
                if snapshot.text_contract_version == HOST_TEXT_CONTRACT_VERSION
                else SourceTape.from_text(
                    item.raw_text, snapshot.text_contract_version
                ).canonical_text
            ),
        )
        for item in snapshot.paragraphs
        if item.story_type == "main" and not item.is_in_table
    )


def _physical_groups(plan: RecognitionPlan) -> Tuple[_PhysicalGroup, ...]:
    grouped = {}
    for block in plan.blocks:
        if block.physical_paragraph_index is None:
            continue
        grouped.setdefault(block.physical_paragraph_index, []).append(block)
    result = []
    for physical_index in sorted(grouped):
        blocks = tuple(sorted(grouped[physical_index], key=lambda item: (item.segment_index, item.block_index)))
        result.append(_PhysicalGroup(
            physical_index=physical_index,
            raw_hash=blocks[0].physical_text_sha256,
            canonical_hash=blocks[0].physical_canonical_text_sha256,
            blocks=blocks,
        ))
    return tuple(result)


def _alignment_score(group: _PhysicalGroup, host: _HostText) -> int:
    if group.raw_hash and group.raw_hash == host.raw_hash:
        return 100
    if group.canonical_hash and group.canonical_hash == host.canonical_hash:
        return 80
    return 0


def _align_groups(
    groups: Sequence[_PhysicalGroup],
    hosts: Sequence[_HostText],
) -> dict[int, tuple[str, Optional[int], int, tuple[int, ...], tuple[str, ...], tuple[str, ...]]]:
    """Return a local alignment state for every source physical paragraph.

    A global dynamic-programming score is still required to preserve document
    order.  Its ambiguity is not global, however: each source group receives
    only the host positions that participate in an optimal monotonic path.
    Therefore one repeated paragraph cannot make unrelated unique paragraphs
    unsafe to bind.
    """
    rows, cols = len(groups), len(hosts)
    forward = [[0] * (cols + 1) for _ in range(rows + 1)]
    for row in range(1, rows + 1):
        for col in range(1, cols + 1):
            match = _alignment_score(groups[row - 1], hosts[col - 1])
            forward[row][col] = max(
                forward[row - 1][col],
                forward[row][col - 1],
                forward[row - 1][col - 1] + match if match else -1,
            )

    backward = [[0] * (cols + 1) for _ in range(rows + 1)]
    for row in range(rows - 1, -1, -1):
        for col in range(cols - 1, -1, -1):
            match = _alignment_score(groups[row], hosts[col])
            backward[row][col] = max(
                backward[row + 1][col],
                backward[row][col + 1],
                backward[row + 1][col + 1] + match if match else -1,
            )

    optimum = forward[rows][cols]
    result = {}
    for row, group in enumerate(groups):
        candidates = []
        for col, host in enumerate(hosts):
            score = _alignment_score(group, host)
            if score and forward[row][col] + score + backward[row + 1][col + 1] == optimum:
                candidates.append((col, score))
        candidate_positions = tuple(position for position, _score in candidates)
        if not candidates:
            result[group.physical_index] = (
                "unmatched", None, 0, (), (), ("PHYSICAL_PARAGRAPH_UNMATCHED",),
            )
            continue
        if len(candidates) > 1:
            result[group.physical_index] = (
                "ambiguous", None, 0, candidate_positions,
                ("PARAGRAPH_ORDER_MATCH",), ("SOURCE_OCCURRENCE_AMBIGUOUS",),
            )
            continue
        position, score = candidates[0]
        evidence = ["PARAGRAPH_ORDER_MATCH"]
        if score == 100:
            evidence.extend(("PHYSICAL_RAW_TEXT_MATCH", "PHYSICAL_HASH_MATCH"))
            status = "matched_unique"
        else:
            evidence.append("PHYSICAL_CANONICAL_TEXT_MATCH")
            status = "matched_review"
        result[group.physical_index] = (status, position, score, candidate_positions, tuple(evidence), ())
    return result


def _bind_physical_groups(
    groups: Sequence[_PhysicalGroup],
    hosts: Sequence[_HostText],
) -> Tuple[PhysicalParagraphBinding, ...]:
    alignments = _align_groups(groups, hosts)
    host_by_position = {position: item for position, item in enumerate(hosts)}
    result = []
    for group in groups:
        status, host_position, score, candidates, evidence, warnings = alignments[
            group.physical_index
        ]
        host = host_by_position[host_position] if host_position is not None else None
        result.append(
            PhysicalParagraphBinding(
                physical_group_id=(
                    group.blocks[0].physical_group_id if group.blocks else ""
                ),
                source_physical_paragraph_index=group.physical_index,
                host_paragraph_index=(
                    host.paragraph.host_paragraph_index if host is not None else None
                ),
                host_paragraph_id=(
                    host.paragraph.host_paragraph_id if host is not None else None
                ),
                status=status,
                score=score,
                candidate_host_paragraph_indexes=tuple(
                    host_by_position[position].paragraph.host_paragraph_index
                    for position in candidates
                ),
                candidate_host_paragraph_ids=tuple(
                    host_by_position[position].paragraph.host_paragraph_id
                    for position in candidates
                ),
                evidence=evidence,
                warnings=warnings,
            )
        )
    return tuple(result)


def bind_physical_paragraphs(
    source_paragraphs: Sequence[tuple[int, str]],
    host_snapshot: HostSnapshot | Mapping[str, Any],
) -> Tuple[PhysicalParagraphBinding, ...]:
    """Align source physical paragraphs before logical recognition starts."""

    snapshot = _coerce_snapshot(host_snapshot)
    _validate_snapshot_contract(snapshot)
    seen_indexes = set()
    groups = []
    for physical_index, raw_text in source_paragraphs:
        if (
            isinstance(physical_index, bool)
            or not isinstance(physical_index, int)
            or physical_index < 0
            or physical_index in seen_indexes
            or not isinstance(raw_text, str)
        ):
            raise BindingError("源物理段落输入无效")
        seen_indexes.add(physical_index)
        groups.append(
            _PhysicalGroup(
                physical_index=physical_index,
                raw_hash=_sha256(raw_text),
                canonical_hash=_sha256(canonicalize_text(raw_text)),
                blocks=(),
            )
        )
    return _bind_physical_groups(tuple(groups), _host_texts(snapshot))


def _bound(
    block: RecognitionBlock,
    host_index: Optional[int],
    host: Optional[_HostText],
    status: str,
    confidence: float,
    evidence: Sequence[str],
    warnings: Sequence[str],
    start: Optional[int] = None,
    end: Optional[int] = None,
    canonical_start: Optional[int] = None,
    canonical_end: Optional[int] = None,
    *,
    plan_id: str = "",
    snapshot: Optional[HostSnapshot] = None,
) -> BoundRecognitionBlock:
    if status == "unresolved":
        host = None
        host_index = None
        start = None
        end = None
        canonical_start = None
        canonical_end = None
    preconditions = {}
    if host is not None and snapshot is not None and status in {"confirmed", "review"}:
        fragment = host.tape.raw_slice_utf16(start or 0, end or 0) if start is not None and end is not None else ""
        canonical_fragment = canonicalize_text(fragment or "") if fragment else ""
        preconditions = {
            "plan_id": plan_id,
            "snapshot_id": snapshot.snapshot_id,
            "document_identity": snapshot.document_identity,
            "document_revision": snapshot.document_revision,
            "host_paragraph_id": host.paragraph.host_paragraph_id,
            "host_paragraph_raw_sha256": host.raw_hash,
            "host_paragraph_canonical_sha256": host.canonical_hash,
            "raw_fragment_sha256": _sha256(fragment or ""),
            "canonical_fragment_sha256": _sha256(canonical_fragment or ""),
            "text_contract_version": snapshot.text_contract_version,
            "offset_encoding": OFFSET_ENCODING,
        }
    return BoundRecognitionBlock(
        block_id=block.block_id,
        block_index=block.block_index,
        physical_group_id=block.physical_group_id,
        physical_paragraph_index=block.physical_paragraph_index,
        host_paragraph_index=host_index,
        host_paragraph_id=host.paragraph.host_paragraph_id if host is not None else None,
        story_id=host.paragraph.story_id if host is not None else None,
        story_type=host.paragraph.story_type if host is not None else None,
        binding_status=status,
        binding_confidence=confidence,
        binding_evidence=tuple(dict.fromkeys(evidence)),
        binding_warnings=tuple(dict.fromkeys(warnings)),
        recommended_action=_recommended_action(status),
        host_raw_start_utf16=start,
        host_raw_end_utf16=end,
        host_canonical_start_utf16=canonical_start,
        host_canonical_end_utf16=canonical_end,
        preconditions=preconditions,
    )


def bind_recognition_plan(
    plan: RecognitionPlan | Mapping[str, Any],
    host_snapshot: HostSnapshot | Mapping[str, Any],
    *,
    strict: bool = False,
) -> RecognitionBinding:
    """Bind a plan to a local host snapshot without calling any editor API.

    Returned offsets refer only to the supplied ``raw_text`` strings.  WPS and
    Word integrations must translate them only after their own API snapshot is
    verified, and must skip any block whose status is not ``confirmed``.
    """
    if isinstance(host_snapshot, HostSnapshotSummary) or (
        isinstance(host_snapshot, Mapping) and host_snapshot.get("summary_type") == "host-snapshot-summary-v1"
    ):
        raise BindingError(
            "HostSnapshotSummary 不能用于绑定",
            details={"path": "$.summary_type", "object_kind": "HostSnapshotSummary"},
        )
    if isinstance(plan, RecognitionPlan):
        _raise_plan_report(validate_recognition_plan(plan, strict=strict))
    else:
        plan = recognition_plan_from_dict(plan, strict=strict)
    if isinstance(host_snapshot, HostSnapshot):
        _raise_snapshot_report(validate_host_snapshot(host_snapshot, strict=strict))
        snapshot = host_snapshot
    else:
        snapshot = host_snapshot_from_dict(host_snapshot, strict=strict)
    if plan.schema_version != "recognition-plan-v1":
        raise UnsupportedContractError(
            "不支持的识别计划 Schema",
            code="UNSUPPORTED_SCHEMA_VERSION",
            details={"path": "plan.schema_version"},
        )
    if plan.integration_contract_version and plan.integration_contract_version != "integration-contract-v1":
        raise UnsupportedContractError(
            "不支持的识别计划协议版本",
            code="UNSUPPORTED_INTEGRATION_CONTRACT",
            details={"path": "plan.integration_contract_version"},
        )
    if plan.locator_version != SDK_SOURCE_LOCATOR_VERSION:
        raise UnsupportedContractError(
            "不支持的来源定位版本",
            code="UNSUPPORTED_SCHEMA_VERSION",
            details={"path": "plan.contracts.source_locator_version"},
        )
    _validate_snapshot_contract(snapshot)
    hosts = _host_texts(snapshot)
    groups = _physical_groups(plan)
    alignments = _align_groups(groups, hosts)
    duplicates = {}
    for host in hosts:
        duplicates[host.raw_hash] = duplicates.get(host.raw_hash, 0) + 1
    host_by_position = {position: item for position, item in enumerate(hosts)}
    physical_paragraphs = _bind_physical_groups(groups, hosts)
    result = []

    for block in plan.blocks:
        if block.physical_paragraph_index is None:
            result.append(_bound(block, None, None, "unresolved", 0.0, (), ("SOURCE_PHYSICAL_PARAGRAPH_MISSING",)))
            continue
        if block.source_locator_status != "confirmed" or not block.locator_verified:
            result.append(_bound(
                block, None, None, "unresolved", 0.0, (),
                tuple(block.source_locator_warnings) + ("SOURCE_LOCATOR_NOT_CONFIRMED",),
            ))
            continue
        alignment = alignments.get(block.physical_paragraph_index)
        if alignment is None:
            result.append(_bound(block, None, None, "unresolved", 0.0, (), ("PHYSICAL_PARAGRAPH_UNMATCHED",)))
            continue
        alignment_status, host_position, score, _candidates, alignment_evidence, alignment_warnings = alignment
        if alignment_status in {"ambiguous", "unmatched"} or host_position is None:
            result.append(_bound(
                block, None, None, "unresolved", 0.0,
                alignment_evidence, alignment_warnings,
            ))
            continue
        host = host_by_position[host_position]
        evidence = list(alignment_evidence)
        warnings = []
        if duplicates.get(host.raw_hash, 0) > 1:
            evidence.append("DUPLICATE_TEXT_DISAMBIGUATED")
        if score == 100:
            start, end = block.raw_start_utf16, block.raw_end_utf16
            fragment = host.tape.raw_slice_utf16(start or 0, end or 0) if start is not None and end is not None else None
            if fragment is None or _sha256(fragment) != block.raw_fragment_sha256:
                result.append(_bound(
                    block, host.paragraph.host_paragraph_index, host, "unresolved", 0.0,
                    evidence, ("SOURCE_TEXT_HASH_MISMATCH",),
                ))
                continue
            evidence.append("SEGMENT_TEXT_MATCH")
            # Convert exact raw UTF-16 offsets through the verified host tape.
            # A raw span may not begin inside a surrogate pair; that condition
            # has already been rejected by ``raw_slice_utf16`` above.
            raw_start_index = _raw_index_for_utf16_offset(host.tape.raw_text, start)
            raw_end_index = _raw_index_for_utf16_offset(host.tape.raw_text, end)
            host_canonical_range = (
                host.tape.canonical_range_for_raw_span(raw_start_index, raw_end_index)
                if raw_start_index is not None and raw_end_index is not None
                else None
            )
            if host_canonical_range is None:
                result.append(_bound(
                    block, host.paragraph.host_paragraph_index, host, "unresolved", 0.0,
                    evidence, ("HOST_CANONICAL_RANGE_UNRESOLVED",),
                ))
                continue
            result.append(_bound(
                block, host.paragraph.host_paragraph_index, host, "confirmed", 1.0,
                evidence + ["SEGMENT_ORDER_MATCH"], warnings, start, end,
                host_canonical_range[0], host_canonical_range[1],
                plan_id=plan.plan_id,
                snapshot=snapshot,
            ))
            continue

        canonical_start = block.canonical_start_utf16
        canonical_end = block.canonical_end_utf16
        raw_span = (
            host.tape.raw_span_for_canonical_range(canonical_start, canonical_end)
            if canonical_start is not None and canonical_end is not None
            else None
        )
        if raw_span is None:
            result.append(_bound(
                block, host.paragraph.host_paragraph_index, host, "unresolved", 0.0,
                evidence + ["PHYSICAL_CANONICAL_TEXT_MATCH"], ("SOURCE_RANGE_UNRESOLVED",),
            ))
            continue
        start_cp, end_cp = raw_span
        start, end = host.tape.raw_offset_utf16(start_cp), host.tape.raw_offset_utf16(end_cp)
        fragment = host.tape.raw_slice_utf16(start or 0, end or 0) if start is not None and end is not None else None
        if fragment is None or _sha256(canonicalize_text(fragment)) != block.canonical_fragment_sha256:
            result.append(_bound(
                block, host.paragraph.host_paragraph_index, host, "unresolved", 0.0,
                evidence + ["PHYSICAL_CANONICAL_TEXT_MATCH"], ("SOURCE_TEXT_HASH_MISMATCH",),
            ))
            continue
        result.append(_bound(
            block, host.paragraph.host_paragraph_index, host, "review", 0.93,
            evidence + ["SEGMENT_TEXT_MATCH", "SEGMENT_ORDER_MATCH"],
            ("RAW_TEXT_NORMALIZED",), start, end, canonical_start, canonical_end,
            plan_id=plan.plan_id,
            snapshot=snapshot,
        ))

    return RecognitionBinding(
        locator_version=SOURCE_LOCATOR_VERSION,
        source_sha256=plan.source_sha256,
        host_type=snapshot.host_type,
        document_identity=snapshot.document_identity,
        host_text_contract_version=snapshot.text_contract_version,
        blocks=tuple(result),
        physical_paragraphs=tuple(physical_paragraphs),
        plan_id=plan.plan_id,
        snapshot_id=snapshot.snapshot_id,
        document_revision=snapshot.document_revision,
        offset_encoding=snapshot.offset_encoding,
    )
