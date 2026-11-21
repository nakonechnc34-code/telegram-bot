---
name: notes-synthesis
description: Turn user-provided notes, fragments, transcripts, brainstorms, or feedback into clear summaries, decisions, actions, themes, risks, and open questions without inventing facts.
---

# Notes Synthesis

## Purpose

Use this skill when the user supplies messy written material and wants it organized. Preserve source meaning, separate confirmed points from interpretation, and make the output useful for the next decision or action.

## Use For

- Meeting notes and recaps.
- Brainstorm cleanup.
- Feedback clustering.
- Decision records.
- Status updates from rough notes.
- Short research or interview synthesis from supplied text.

## Operating Protocol

1. Identify the intended output: recap, brief, decision record, action list, or themes.
2. Extract durable content: decisions, actions, reasons, risks, dates, owners, blockers.
3. Collapse duplicates while preserving dissent and uncertainty.
4. Label missing owners/dates as unassigned or not provided.
5. Mark inference explicitly when something is implied but not stated.
6. Produce the shortest structure that preserves usefulness.

## Output Shape

```markdown
## Summary
- [High-signal takeaway.]

## Decisions
- [Decision and rationale.]

## Action Items
| Owner | Task | Due |
| --- | --- | --- |
| [Owner or Unassigned] | [Action] | [Date or Not provided] |

## Themes
- [Theme]: [supporting detail.]

## Open Questions
- [Question.]
```

## Guardrails

- Always respond in user language
- Do not invent decisions, owners, dates, quotes, or consensus.
- Do not treat discussion as commitment unless the notes say so.
- Minimize sensitive details when summarizing for broader audiences.
- If input is too long for the context, ask for chunks or synthesize the supplied excerpt only.

## Good Defaults

- For meetings, prioritize outcomes and action items.
- For brainstorms, group ideas and add evaluation criteria.
- For feedback, separate repeated patterns from isolated comments.
