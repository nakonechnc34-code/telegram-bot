---
name: product-brief
description: Create concise product briefs that define problem, users, outcome, scope, non-goals, risks, metrics, dependencies, and next decisions from supplied context.
---

# Product Brief

## Purpose

Use this skill to turn a product idea, stakeholder request, or messy notes into a decision-ready brief. The brief should help product, design, engineering, and leadership align on what is worth building and why.

## Use For

- Feature one-pagers.
- MVP scoping.
- PRD-lite drafts.
- Customer feedback to product direction.
- Leadership review documents.
- Pre-build alignment before design or engineering.

## Operating Protocol

1. Start with the user problem, not the proposed solution.
2. Identify target user, desired outcome, evidence, and constraints.
3. Separate scope from non-goals.
4. Define a first useful version.
5. Add measurable success signals and guardrails when possible.
6. List risks, dependencies, and open questions that affect execution.

## Output Shape

```markdown
## Summary
[Problem, user, direction, intended outcome.]

## Decision Needed
[What should be approved or clarified.]

## Target User
[Specific segment.]

## Problem
[Pain or opportunity.]

## Scope
- [Included behavior.]

## Non-Goals
- [Excluded behavior.]

## Success Signals
- Primary: [observable outcome]
- Guardrail: [what should not degrade]

## Risks And Dependencies
- [Risk/dependency]: [impact]

## Open Questions
- [Question]

## Next Steps
1. [Action]
```

## Guardrails

- Always respond in user language
- Do not invent customer evidence, metrics, deadlines, or stakeholder decisions.
- If evidence is missing, label the brief as assumption-driven.
- Keep it shorter than a full PRD unless the user asks for detail.
- Avoid solution detail until problem and outcome are clear.

## Good Defaults

- Recommend an MVP when uncertainty is high.
- Make tradeoffs explicit.
- Include enough acceptance direction for engineering and QA to respond.
