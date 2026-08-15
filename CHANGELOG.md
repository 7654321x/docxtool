# Changelog

## 5.4.1 - 2026-08-15

- Added account-scoped local SQLite format profiles and a WPS format-settings dialog with named template creation, selection, editing, and deletion while preserving the immutable system default.
- Made preview and one-click formatting read the same active template configuration, and added focused UI, runtime, persistence, and account-isolation regression coverage.
- Fixed Reader book restoration, viewport-based navigation, line-by-line playback, visibility pause/resume, and persisted progress behavior without storing complete book text in SQLite.
- Updated WPS packaging resources, regression rules, and the GitHub publish allowlist for the format-settings and Reader changes.

## 5.4 - 2026-08-14

- Consolidated project documentation to eleven current root files, moved WPS UI designs into `docs/design`, folded architecture, SDK binding, release, validation, and recognition gates into their owned documents, and removed obsolete login, outbox, version, EXE, and duplicate-document descriptions without changing runtime behavior.
- Added a fully local TXT Reader domain under `apps/reader`, with UTF-8/UTF-8 BOM/GB18030 import, chapter indexing, per-book progress, local settings, and SQLite metadata that never stores complete book text.
- Added WPS Reader TaskPane mode with raw TXT loopback import, bounded content blocks, chapter/block navigation, elapsed-time `requestAnimationFrame` scrolling, focused keyboard shortcuts, style controls, and internal collapse/reveal.
- Kept Reader outside the public account, formatting authorization, HostBridge, CommandMonitor, Core, Recognition, Normalization, and Engine chains while reusing existing loopback credential and Origin protection.
- Added Reader privacy, architecture, transaction-consistency, WPS adapter, TaskPane mode, and playback regression coverage; updated frozen-package resources and GitHub publish allowlists.
- Split document configuration, diagnostics, and shared errors into owned modules while keeping `style_config.py` as a compatibility facade; retired the old PyQt5 configuration UI without changing the PySide2 WPS client.
- Removed the SDK model/validator import-time cycle through a lazy validation boundary and extracted pure WPS transaction and Control transport helpers; public schemas, JSON fields, and compatibility imports remain unchanged.

## 5.3 - 2026-08-13

- Added a WPS “添加版头” flow that directly generates or transactionally replaces a single-agency letterhead in the current document without recognition, one-click formatting, or public authorization.
- Added source-letterhead field extraction, page-width-adaptive red agency marks, straight/star separators, exact two-body-line title spacing, and explicit rejection of unsupported joint source letterheads.
- Kept legacy `.doc/.wps` letterhead inspection non-publishing while allowing a confirmed add operation to produce the same-name `.docx` with rollback protection.
- Made Recognition the final authority for semantic paragraph types; heading-family sibling evidence is now resolved by the existing context, candidates, and Beam decoder instead of post-recognition normalization.
- Built the final `DocumentStructure` only after normalization, tail ordering, and diagnostics consistency synchronization so structure, paragraph order, and final types share one state.
- Added the internal `NORMALIZE`, `PRESERVE_LAYOUT`, and `PRESERVE_OBJECT` layout policies, inferred once from final structure and physical document facts.
- Preserved Tab, repeated spaces, full-width spaces, and NBSP in repeated manual-column rows on real attachment pages while still applying the final attachment font, size, line spacing, and paragraph style.
- Made structural paragraph rendering fail fast with `ExportError` instead of silently degrading titles, headings, signatures, or attachment structures into body text.
- Added anonymous generated-DOCX regressions for attachment manual columns, ordinary attachment text, body key-value lines, all processing modes, protected objects, semantic-type finality, and final tail structure ordering.

## 5.2.2 - 2026-08-13

- Recognized Word/WPS native automatic-numbering headings across levels one through four without requiring bold formatting, while preserving numbering definitions and source locators for safe output decisions.
- Made WPS one-click formatting remove native heading numbering and rebuild editable text numbering with the configured heading font, size, and weight; ordinary automatic body lists remain preserved.
- Removed terminal Chinese full stops from standalone headings at all four levels while retaining punctuation that separates an inline heading from body text.
- Added a PySide2 custom title bar, shared D branding for login, settings, taskbar, Alt+Tab, and system tray, plus remember-password, auto-login, startup, and account-recovery controls.
- Hardened WPS account rejection, durable result outbox cleanup, bounded `panel_ready` completion, launcher resource cleanup, loopback disconnect handling, and Chinese offline feedback.
- Extended WPS sessions to seven days, bounded WPS Argon2 concurrency to two operations, moved password rehashing outside SQLite write locks, and raised the WPS per-IP login limit without weakening password parameters.

## 5.2.1 - 2026-08-12

- Rebuilt the WPS login/register experience with PySide2 Qt Widgets and QSS, adding DPAPI-backed remember-password preferences, user-selected auto-login, and corruption recovery while keeping manual login as the default.
- Extended newly issued WPS sessions to seven days without migrating existing expiries, while keeping heartbeat non-renewing.
- Bounded WPS Argon2 work to two concurrent operations per process, moved password rehash computation outside the SQLite write transaction, and raised only the WPS per-IP login limit to 300 requests per 10 minutes.
- Hardened the WPS loopback credential boundary with same-origin runtime configuration and exact browser-origin validation.
- Fixed late `panel_ready` completion, failed TaskPane reopen recovery, Web task lifecycle handling, and DOCX download response validation.
- Added local-account corruption recovery and a durable SQLite format-result outbox.
- Added Windows WPS/EXE release gates and corrected privacy-sensitive WPS log fields and lifecycle event names.

## 5.2 - 2026-08-12

- Added an independent WPS account service with user registration and login, device and session lifecycle management, heartbeat, controlled formatting authorization, result reporting, and dedicated SQLite storage.
- Added a unified administrator workspace for Web runtime status, WPS users, devices, online activity, and account or device enable/disable actions.
- Added WPS client login and account persistence, runtime session refresh, authorization-aware formatting, pending result delivery, and explicit network or account-state feedback.
- Strengthened transactional handling for `.doc` and `.wps` conversion, document replacement, rollback, and host-side formatting while preserving single-thread WPS document access.
- Added reproducible WPS executable build inputs, public API and server contracts, deployment guidance, and focused Python and JavaScript regression coverage.
- Improved front-matter role/name recognition using document-wide title, date, salutation, style, alignment, and name-shape evidence without person or organization allowlists.

## 5.1 - 2026-08-10

- Replaced high-frequency PluginStorage command polling with a single-slot HostBridge long-request transport while keeping all WPS document objects on the Host thread and Core work serialized by the existing monitor.
- Stabilized the background launcher with a fixed `127.0.0.1:3889` add-in origin, explicit port-conflict failure, no automatic WPS launch, and safe Ribbon UI ownership across Bootstrap reloads.
- Completed the first-open TaskPane layout path with one `panel_ready` native workspace recalculation, versioned pane replacement, bounded geometry diagnostics, sentence-case display states, and the WPS-style TaskPane icon.
- Expanded stage-specific, document-scoped WPS diagnostics and split normal console logs to stdout while reserving stderr for warnings and errors without changing file-log content.
- Preserved native Word/WPS automatic-list heading evidence when a bold heading sentence and ordinary body share one physical paragraph, with source locator continuity and no split for ordinary list prose.
- Added HostBridge, launcher, Ribbon, TaskPane, logging, segmentation, SDK locator, privacy, and release-manifest regression coverage without changing the public SDK schema or DocxTool Engine boundary.

## 5.0 - 2026-08-10

- Stabilized the WPS bootstrap, Host Runtime, TaskPane, Control Server, and single-thread command-monitor chain with stage-specific privacy-safe diagnostics.
- Expanded recognition preview coverage to confirmed and review-only bindings while preserving Range preconditions, rollback, and unresolved-item safety.
- Routed WPS one-click formatting through the authoritative DocxTool importer, recognition, normalization, and Engine pipeline with numbering and safe punctuation enabled by default.
- Preserved native WPS list-heading hierarchy when parent-child structure supports a visible first-level heading.
- Added transactional silent `.doc/.wps` upgrades before preview or formatting, with one WPS conversion, same-name collision protection, content verification, recovery, and permanent `.docx` publication.
- Added WPS Python and JavaScript runtime regression gates, updated the public release manifest, and retained the existing SDK and Core architecture boundaries.

## 4.0 - 2026-08-04

- Released the recognition-first wheel contract for WPS, Office.js, VSTO, and other local hosts while keeping formatting writes inside each host adapter.
- Stabilized `RecognitionRequest`, `RecognitionPlan`, `HostSnapshot`, and `RecognitionBinding` with JSON Schema validation, UTF-16 source locators, privacy-safe defaults, stable IDs, and write preconditions.
- Fixed exporter compatibility so an internal `TypeError` is never hidden by a second export attempt, and preserved inspectable legacy exporter signatures with one call only.
- Removed Web and document-layer reverse dependencies by moving shared letterhead, punctuation, structure analysis, and models to neutral modules while retaining public compatibility facades.
- Added the complete Chinese project file tree, updated the GitHub publish allowlist, and retained Python 3.8 through 3.10 compatibility.
- Verified 1269 Python tests on Python 3.8 and 3.10, 10 Node tests, Ruff, independent imports, 55 documents across three processing modes, 50+5 structural regression documents, and 239 rendered review pages.

## 3.0 - 2026-08-03

- Hardened four-character front-matter name detection with strong/weak name shapes and complete structural context, while preserving compact role-name forms without name or organization allowlists.
- Unified semantic-colon label start/end offsets across recognition and rendering so prefixed time, ratio, and version expressions remain normal weight.
- Reclassified strict and normalize comparison findings only when the processing-mode contract and normalized character conservation both prove the differences are expected.
- Bound the formal 2.9 commit, tree, and clean wheel in the public Phase B manifest, including normalized wheel-content comparison evidence.
- Verified 1246 Python tests on Python 3.8 and 3.10, 10 Node tests, wheel-only SDK behavior, all three 50+5 processing modes, and targeted role/colon visual rendering.

## 2.9 - 2026-08-03

- Tightened front-matter role/name parsing so role expressions must end at the person-name boundary and remain supported by title, date, or salutation structure.
- Made numeric-colon detection whitespace-aware across spaces, tabs, NBSP, full-width spaces, and other Unicode whitespace while preserving original offsets.
- Limited colon-label bolding to the true semantic label range when a numeric time or ratio precedes a later label.
- Removed private fixture metadata from public Phase B reports and added release-time metadata scanning.
- Verified Python 3.8 and 3.10 with 1206 tests each, 11 Node tests, wheel-only SDK behavior, all three 50+5 processing modes, relationship integrity, and targeted visual rendering.

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
