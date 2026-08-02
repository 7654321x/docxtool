# Changelog

## 2.8 - 2026-08-03

- Hardened front-matter role/name recognition with structural title, date, and salutation anchors while rejecting document-shaped title and body false positives.
- Unified semantic-colon detection across recognition and rendering so numeric ratios and times are not treated as labels or bolding boundaries.
- Stabilized partial SDK locator ordering, overlap handling, segment counts, JSON round-trips, and host binding without changing published field names.
- Added reproducible 2.2/2.6/2.7/current manifests and clustered the former 60 P1 findings to one shared attachment-pagination regression plus comparison-attribution cascades.
- Verified 1164 Python tests, 11 Node tests, Ruff, compile checks, wheel-only SDK installation, and all 50 standard plus 5 special DOCX fixtures.

## 2.7 - 2026-08-02

- Completed the remaining Phase A-3 mechanical module boundaries for recognition, Web, and document export while retaining the established compatibility facades and behavior.
- Prevented front-matter role/date metadata from being overwritten by title continuation or colon-body candidates.
- Fixed attachment pagination when a new attachment marker follows a title without body content, and preserved same-line signature/date source ranges during tail restructuring.
- Ordered SDK segment metadata by original UTF-16 source spans after tail normalization so verified host ranges are not reported as overlapping.
- Regenerated all 50 standard and 5 special regression documents; full Python tests, Ruff, compile checks, structural audits, and targeted page renders passed.

## 2.6 - 2026-08-02

- Completed Phase A-3 Module 1 by reducing `DocxImporter.load` to a compatibility facade and moving the unchanged document call chain into focused pipeline modules.
- Extracted processing options, paragraph materialization, Legacy stream orchestration, and Core classifier adaptation while preserving old imports and monkeypatch paths.
- Verified 202 directly related tests and 18 strict, structural, and normalize migration snapshots with no structural, recognition, package, or relationship differences.

## 2.5 - 2026-08-02

- Completed the Phase A mechanical importing and segmentation responsibility boundaries while preserving the existing importer and pipeline compatibility facades.
- Added focused physical-format extraction, source-span partitioning, and segmentation conservation modules.
- Verified strict, structural, and normalize equivalence with no package, relationship, document-structure, recognition-input, or source-span conservation differences.

## 2.4 - 2026-08-02

- Completed Phase A document-chain extraction by separating source reading, recognition helper boundaries, segmentation, and normalization orchestration while preserving the existing public importer facade.
- Added focused regression coverage for the extracted document-chain modules and a reusable equivalence snapshot tool for before/after migration verification.
- Verified that the Phase A refactor preserves strict, structural, and normalize processing behavior across the standard and special DOCX regression sets.

## 2.3 - 2026-08-01

- Split Web request lifecycle, authorization, upload, monitor, page, health, and task-queue orchestration into focused modules while keeping `web/app.py` as the compatibility facade.
- Moved Web worker queue consumption and in-memory processing-state updates behind the task worker facade.
- Moved spawned subprocess timeout handling and child-result collection into the task worker boundary.
- Moved subprocess entry result writing and fallback error shaping into the task worker boundary.
- Moved one-time worker thread startup state handling into the task worker boundary.
- Added an application-layer uploaded DOCX task processor facade so Web app code no longer owns the import/export result orchestration body.
- Moved legacy importer scoring context models under `document/recognition/legacy` while preserving importer re-exports.
- Moved image/caption physical facts and inline token extraction helpers under `document/importing`.
- Moved section property and header/footer relationship collection helpers under `document/importing`.
- Moved literal numbering-prefix extraction under `document/importing` while preserving importer compatibility wrappers.
- Fixed authoritative recognition ownership so tail normalization no longer reclassifies body paragraphs after recognition.
- Weakened legacy importer influence so it cannot hard-veto front metadata, headings, signature dates, or attachment decisions.
- Made Beam Search diagnostics come from the final winning path instead of a temporary best prefix.
- Replaced the fixed 12-paragraph front scan stop with a soft threshold and stronger post-threshold evidence requirements.
- Updated DOCX regression paths for the current `test_docx/tset1` and `test_docx/test2` layout.

## 2.2 - 2026-08-01

- Added shared colon-structure evidence for recipients, salutations, body labels, key-value fields, and explanatory prose.
- Strengthened front-matter/body boundaries and heading-family consistency checks for duplicate, reversed, skipped, or orphaned numbering.
- Separated likely heading application from review certainty so conflicted numbered headings can still be applied while surfacing `HEADING_SEQUENCE_CONFLICT`.
- Added regression coverage for generalized colon structures, inline salutation/body splits, organization labels, structural key-value fields, and heading-sequence review.
- Updated recognition architecture docs, collaboration rules, and GitHub publish allowlist for the new recognition module.

## 2.1 - 2026-08-01

- Centralized runtime package version reporting so Web `/version`, SDK manifest, CLI, and wheel metadata stay aligned.
- Added a Web and SDK architecture DAG document for queue, worker, subprocess, recognition-plan, host-snapshot, and binding boundaries.
- Added regression tests for version consistency and architecture documentation coverage.
- Updated the GitHub publish allowlist to include the new runtime version module and DAG documentation.

## 2.0 - 2026-08-01

- Added `integration-contract-v1` for host-neutral recognition and binding integration.
- Added SDK manifest capability negotiation, `RecognitionRequest`, stable plan/block/snapshot/binding IDs, JSON Schema files, JSON validation helpers, and structured SDK errors.
- Hardened SDK protocol validation with `ValidationReport`, strict JSON boolean handling, `HostSnapshotSummary`, schema-name loading, cross-field semantic checks, binding state invariants, and safer error detail allowlists.
- Added the `docxtool-sdk` CLI with `manifest`, `recognize`, `bind`, and `validate` commands while keeping `docxtool-recognize` compatible.
- Extended host binding output with `RecognitionBinding` preconditions so WPS, Microsoft Word, and other hosts can verify real editor ranges before applying formatting.
- Documented that this release prepares the wheel/SDK contract only; WPS and Microsoft Word host adapters remain separate future work.

## 1.9 - 2026-07-31

- Simplified GitHub publishing to one default command covering the allowlist, sensitive-file scan, commit, push, and remote-head verification.
- Made dry-run and full test verification optional through `-DryRun` and `-Verify`, while retaining the clean temporary clone and no-force-push protections.

## 1.8 - 2026-07-31

- Reworked DOCX regression comparison with heading-content alignment, source/output/template attribution, character-based indent comparison, and protected-caption provenance checks.
- Recognized malformed Chinese first-level prefixes such as `二.标题` without confusing `一是/二是` prose, and rebuilt them through the existing numbering option.
- Kept the configured gap for opening salutations while removing inherited before/after spacing from repeated salutations after the speech body has started.

## 1.7 - 2026-07-31

- Added conservative multi-boundary logical segment candidates and complete segment-group source locators.
- Added effective run formatting resolution across direct properties, styles, inheritance, document defaults and theme fonts, including East Asian font and coverage diagnostics.
- Extended host binding with canonical host offsets and fragment UTF-16 length, plus a shared host-text-v1 gold contract for WPS integrations.

## 1.6 - 2026-07-31

- Made recognition-plan host binding locally ambiguity-aware so unresolved repeated text does not invalidate unrelated physical paragraphs.
- Added run-intersection formatting facts for logical fragments, the `host-text-v1` canonical text contract, and complete logical-segment counts.

## 1.5 - 2026-07-31

- Added source-range based logical fragment locators, including raw and canonical UTF-16 coordinate definitions.
- Added SDK v2 locator fields, explicit text opt-ins, and a host-neutral recognition-plan binding API with ambiguity rejection.
- Added regression coverage for mixed physical paragraphs, duplicate text, host paragraph shifts, canonical normalization, Unicode surrogate pairs, and CLI binding output.

## 1.4 - 2026-07-30

- Added a reusable Chinese official-document formatting and recognition specification for WPS and third-party AI integrations.

## 1.3 - 2026-07-29

- Added a stable, local-only `docxtool.sdk` recognition API for third-party integrations.
- Added the `docxtool-recognize` command for writing redacted JSON recognition plans from DOCX snapshots.
- Kept the existing web service, recognition rules, formatting engine, and DOCX export flow unchanged.

## 1.2 - 2026-07-29

- Added Python 3.8 compatibility for Windows 7 while retaining Python 3.10 support.
- Rebuilt production and development dependency locks from Python 3.8.
- Added dual-version CI and Windows startup compatibility checks.
- Completed authoritative structured document recognition with document-head analysis, global context, heading families, constrained decoding, diagnostics, and review signals.
- Clarified strict, structural, and normalize processing boundaries; structural mode now repairs only reliable document boundaries while preserving visible text by default.
- Improved letterhead, title, heading, numbering, punctuation, signature, attachment, page-number, table, section, and DOCX relationship handling.
- Added protected user authentication, private template/task ownership, deployment hardening, and Cloudflare Pages proxy coverage.
- Added batch DOCX regression comparison, deterministic visual rendering checks, and reusable recognition benchmarks.

## 1.1 - 2026-07-29

- Added account authentication, session isolation, anonymous-resource migration, and protected template ownership.
- Upgraded document recognition with structured candidates, context-aware decoding, diagnostics, and review signals.
- Improved official-document formatting for letterheads, headings, signatures, attachments, numbering, punctuation, and layout preservation.
- Added production deployment materials, dependency locks, security hardening, automated regression tooling, and batch document validation.
- Improved the administrator workspace, frontend authentication experience, and Cloudflare Pages proxy integration.
