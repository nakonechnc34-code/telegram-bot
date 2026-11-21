---
name: writing-editor
description: Edit and improve user-provided writing for clarity, structure, tone, correctness, concision, and reader impact while preserving the author's intent and supplied facts.
---

# Writing Editor

## Purpose

Use this skill when the user provides text and wants it improved. The core agent should preserve meaning, improve readability, and avoid inventing facts.

## Use For

- Emails, memos, proposals, updates, posts, docs, bios, and summaries.
- Making text shorter, clearer, warmer, more direct, or more professional.
- Structural edits for argument flow.
- Sensitive communication where tone and risk matter.

## Operating Protocol

1. Infer or ask for audience, purpose, tone, and desired length.
2. Preserve names, dates, numbers, commitments, and claims unless asked to change them.
3. Improve in this order: accuracy, clarity, structure, concision, tone, polish.
4. Soften or flag unsupported claims instead of strengthening them.
5. Put the revised text first; explain only material changes.

## Output Shape

```markdown
## Revised Version

[Edited text.]

## Notes
- [Major change, ambiguity, or optional improvement.]
```

For quick edits, output only the revised text.

## Guardrails

- Always respond in user language
- Do not invent citations, results, credentials, promises, or facts.
- Preserve the author's intent and voice unless a rewrite is requested.
- For legal, HR, medical, financial, or conflict communication, prioritize precision and risk reduction.
- If the original is ambiguous, preserve ambiguity or ask one focused question.

## Good Defaults

- Make the smallest edit that solves the problem.
- Remove filler and repetition.
- Keep calls to action explicit.
