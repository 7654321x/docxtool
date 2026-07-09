---
name: official-document-formatting
description: Format Chinese official documents and speech materials according to the current docxtool public-document rules. Use when the user provides an article, draft, DOCX, speech, report, notice, briefing, meeting material, or government-style text and asks Hermes to adjust fonts, headings, numbering, spacing, title/date/author layout, body paragraphs, special bolding, attachments, signatures, or page format. Do not use for frontend/API/template integration work.
---

# Official Document Formatting

Use this skill to format Chinese official-document drafts. Focus only on document content and layout rules. Do not discuss frontend pages, backend APIs, preset storage, upload headers, or database work unless the user explicitly asks for system implementation.

## Core Workflow

1. Identify document structure before changing format:
   - title / title continuation
   - role-name line, author line, date line
   - salutation
   - level 1-4 headings
   - body paragraphs
   - inline numbered body points such as `一是` / `二是` / `三是`
   - attachment notes, attachment pages, signature organization, signature date
2. Apply formatting with minimal content changes. Preserve wording unless the user asks for rewriting.
3. After formatting, check these failure points:
   - no duplicated paragraphs
   - no extra blank paragraph between role-name and date
   - date has the only one-line gap before正文
   - heading numbering has no extra space after the marker
   - `一是/二是/三是` body points are not converted into headings
   - title/date/author lines are not misclassified as正文

## Page Defaults

- Paper: A4.
- Margins: top `3.7cm`, bottom `3.5cm`, left `2.8cm`, right `2.6cm`.
- Grid: 22 lines per page, 28 characters per line.
- Line spacing: fixed `28磅`.
- Body paragraph spacing: before `0`, after `0`, unless a structural rule below overrides it.
- Page number: Songti, 四号, format `— 1 —`, odd pages right and even pages left when supported.

## Font And Paragraph Defaults

| Element | Font | Size | Bold | Alignment | Indent / Spacing |
| --- | --- | --- | --- | --- | --- |
| 主标题 | 方正小标宋简体 | 二号 | false | 居中 | no first-line indent |
| 一级标题 | 黑体 | 三号 | false | 左对齐 | first-line indent 2 chars |
| 二级标题 | 楷体_GB2312 | 三号 | true | 左对齐 | first-line indent 2 chars |
| 三级标题 | 仿宋_GB2312 | 三号 | true | 左对齐 | first-line indent 2 chars |
| 四级标题 | 仿宋_GB2312 | 三号 | false | 左对齐 | first-line indent 2 chars |
| 正文 | 仿宋_GB2312 | 三号 | false | 两端对齐 | first-line indent 2 chars |
| 称呼 | 仿宋_GB2312 | 三号 | false | 左对齐 | first-line indent 2 chars; before 1 line |
| 日期行 | 楷体_GB2312 | 三号 | false | 居中 | see head spacing rules |
| 作者行 | 楷体_GB2312 | 三号 | true | 居中 | after 0 |
| 职务姓名 | 楷体_GB2312 | 三号 | true | 居中 | after 0 |
| 附件说明 | 仿宋_GB2312 | 三号 | false | 左对齐 | before 1 line; left indent 2 chars |
| 落款署名 | 仿宋_GB2312 | 三号 | false | 右对齐 | before 1 line |
| 落款日期 | 仿宋_GB2312 | 三号 | false | 右对齐 | right indent 2 chars |

## Head Area Rules

- Common order A: `title -> role-name -> date -> body`.
- Common order B: `title -> date -> author -> body`.
- For speech and meeting materials, a line such as `区政协副主席   杨明远` after the title is a role-name line, not a title continuation.
- For titles containing `发言`, `讲话`, `致辞`, or `主持词`, a short Chinese name line after the title is usually a role-name line.
- A date line may be written as `（2026年7月  日）`; missing day digits still counts as a date line.
- If both role-name/author and date are present:
  - role-name/author and date must be adjacent;
  - do not insert a blank paragraph between them;
  - role-name/author paragraph after spacing is `0`;
  - date paragraph after spacing is `1 line`.
- The one-line visual gap belongs after the date, before the first body paragraph or first level-1 heading.
- Prefer paragraph spacing for the date gap. Do not create an extra blank paragraph unless the output system cannot express paragraph spacing.

## Numbering Rules

- Level 1 heading: `一、标题`, `二、标题`, `三、标题`.
- There is no space after `一、`.
- Level 2 heading: `（一）标题`.
- Level 3 heading: `(1)标题`.
- Level 4 heading: `1.标题`.
- Strip duplicated existing heading markers before inserting normalized numbering.
- Do not treat body phrases such as `一是`, `二是`, `三是`, `一要`, `二要` as level-1 headings.

## Body And Special Bold Rules

- Body uses 仿宋_GB2312, 三号, two-character first-line indent, justified alignment.
- Inline body points beginning with `一是` / `二是` / `三是` or similar numbered-bold phrases stay as body paragraphs.
- For `一是/二是/三是` body points, bold the lead sentence up to the first `。` when appropriate.
- Do not also apply a separate report-first-sentence bold rule to the same paragraph. Two overlapping run-rewrite rules can duplicate the text.
- If a paragraph begins with a fixed keyword and colon, such as `责任单位：`, bold only the keyword through the colon, then keep the rest normal.
- Preserve original paragraph text. Formatting must never duplicate a sentence or paragraph.

## Attachments And Signature

- Attachment note uses body font and is left aligned. The first attachment note has before spacing of 1 line.
- Attachment item continuation aligns to the text after the item number.
- Attachment body mark starts on a new page when needed.
- Signature organization is right aligned with before spacing of 1 line.
- Signature date is right aligned with right indent 2 chars.

## Validation Checklist

Before returning a formatted document or final instructions, verify:

- Title is centered and uses 方正小标宋简体 二号.
- Role-name/author and date are correctly classified.
- If role-name and date both exist, they are adjacent with no blank line between them.
- Date line has after spacing of 1 line.
- First body paragraph or first level-1 heading starts after the date gap.
- Level-1 headings are `一、标题`, not `一、 标题`.
- `一是/二是/三是` paragraphs appear once only and remain body paragraphs.
- Body paragraphs use 仿宋_GB2312 三号, first-line indent 2 chars, justified.
- There are no unintended content edits, lost paragraphs, or repeated tail paragraphs.

## When The User Provides Only Plain Text

Return either a formatted DOCX when tools are available, or provide a structured formatting plan with the recognized paragraph types and required formatting. If exact Word rendering cannot be verified, say so briefly and still perform text-level and structure-level checks.
