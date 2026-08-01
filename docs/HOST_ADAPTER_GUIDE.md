# Host Adapter Guide

This guide describes how WPS, Microsoft Word Office.js, Word VSTO/COM, and other
local editors can use the DocxTool SDK contract. It is not a plugin
implementation.

## Shared Flow

1. Export or save the currently open document as a temporary local DOCX snapshot.
2. Call `docxtool-sdk recognize --source snapshot.docx --output plan.json`.
3. Build a `host-snapshot-v1` object from the current editor paragraphs.
4. Validate both JSON files with `docxtool-sdk validate`.
5. Optionally write a text-free `docxtool-sdk summarize-snapshot` report for UI
   diagnostics; never pass that summary to binding.
6. Call `docxtool-sdk bind --plan plan.json --snapshot snapshot.json --output binding.json`.
7. For each `confirmed` block, locate the host paragraph by `host_paragraph_id`.
8. Re-read the current host paragraph text and validate binding preconditions.
9. Create a real host Range for the raw span.
10. Read the Range text back, hash raw/canonical fragment text, and compare with
   preconditions.
11. Apply formatting only after every check passes.

`review` blocks are preview-only. `unresolved` blocks are skipped and must not
carry executable host spans.

## WPS JS Pseudocode

```javascript
const manifest = await localAgent.run("docxtool-sdk", ["manifest"]);
assert(manifest.data.integration_contract_versions.includes("integration-contract-v1"));

const docxPath = await wpsAdapter.exportActiveDocumentSnapshot();
await localAgent.run("docxtool-sdk", [
  "recognize",
  "--source", docxPath,
  "--output", "plan.json"
]);

const snapshot = await wpsAdapter.createHostSnapshot({
  schema_version: "host-snapshot-v1",
  text_contract_version: "host-text-v1",
  offset_encoding: "utf16_code_unit"
});

await localAgent.writeJson("snapshot.json", snapshot);
const binding = await localAgent.run("docxtool-sdk", [
  "bind",
  "--plan", "plan.json",
  "--snapshot", "snapshot.json"
]);

for (const block of binding.data.blocks) {
  if (block.binding.status !== "confirmed") continue;
  const paragraph = await wpsAdapter.getParagraphById(block.host_target.host_paragraph_id);
  const rawText = await paragraph.getVisibleText();
  wpsAdapter.verifyPreconditions(rawText, block.preconditions);
  const range = await paragraph.createRangeFromUtf16Span(block.host_target.raw_span);
  const rangeText = await range.getText();
  wpsAdapter.verifyFragment(rangeText, block.preconditions);
  await wpsAdapter.applyFormat(range, block.block_id);
}
```

## Microsoft Word Office.js Pseudocode

```javascript
await Word.run(async (context) => {
  const docxPath = await wordAdapter.saveLocalSnapshot(context.document);
  await localAgent.run("docxtool-sdk", ["recognize", "--source", docxPath, "--output", "plan.json"]);

  const paragraphs = await wordAdapter.readMainStoryParagraphs(context);
  const snapshot = wordAdapter.buildHostSnapshot({
    snapshot_id: crypto.randomUUID(),
    host: { kind: "microsoft-word", platform: "office-js" },
    paragraphs
  });

  await localAgent.writeJson("snapshot.json", snapshot);
  const binding = await localAgent.run("docxtool-sdk", [
    "bind", "--plan", "plan.json", "--snapshot", "snapshot.json"
  ]);

  for (const block of binding.data.blocks) {
    if (block.binding.recommended_action !== "verify_host_range") continue;
    const paragraph = wordAdapter.findParagraphByHostId(block.host_target.host_paragraph_id);
    const freshText = await wordAdapter.readParagraphText(paragraph);
    wordAdapter.verifyPreconditions(freshText, block.preconditions);
    const range = wordAdapter.createRangeFromRawUtf16Span(paragraph, block.host_target.raw_span);
    const rangeText = await wordAdapter.readRangeText(range);
    wordAdapter.verifyFragment(rangeText, block.preconditions);
    wordAdapter.applyFormat(range, block.block_id);
  }
});
```

## Word VSTO/COM Pseudocode

```csharp
var manifest = LocalAgent.RunJson("docxtool-sdk", "manifest");
ContractAssert.Supports(manifest, "integration-contract-v1");

var docxPath = WordAdapter.SaveTemporaryDocxSnapshot(Application.ActiveDocument);
LocalAgent.RunJson("docxtool-sdk", "recognize", "--source", docxPath, "--output", "plan.json");

var snapshot = WordAdapter.CreateHostSnapshot(Application.ActiveDocument);
LocalAgent.WriteJson("snapshot.json", snapshot);
var binding = LocalAgent.RunJson("docxtool-sdk", "bind", "--plan", "plan.json", "--snapshot", "snapshot.json");

foreach (var block in binding.Data.Blocks) {
    if (block.Binding.Status != "confirmed") continue;
    var paragraph = WordAdapter.FindParagraphByHostId(block.HostTarget.HostParagraphId);
    var freshText = WordAdapter.ReadVisibleParagraphText(paragraph);
    ContractAssert.VerifyPreconditions(freshText, block.Preconditions);
    var range = WordAdapter.CreateRangeFromUtf16Span(paragraph, block.HostTarget.RawSpan);
    var rangeText = WordAdapter.ReadRangeText(range);
    ContractAssert.VerifyFragment(rangeText, block.Preconditions);
    WordAdapter.ApplyFormat(range, block.BlockId);
}
```

## Adapter Responsibilities

The host adapter must implement:

- Current-document snapshot export.
- Visible paragraph text extraction.
- Stable `snapshot_id` and `host_paragraph_id` generation for one snapshot.
- UTF-16 code unit span to host Range conversion.
- Real Range read-back verification.
- Formatting write operations.
- User-facing preview or review UI.
- Undo, backup, save, and error recovery policies.

The DocxTool SDK does not implement any of these host-specific operations.
