---
name: task-planner
description: Break a goal or messy request into an executable plan with phases, tasks, dependencies, risks, acceptance checks, and immediate next actions.
---

# Task Planner

## Purpose

Use this skill when the user needs to move from intent to execution. The plan should reduce ambiguity, expose dependencies, and make the first steps obvious.

## Use For

- Project plans.
- Implementation checklists.
- Ticket breakdowns.
- Migration plans.
- Launch or operational plans.
- Personal or team task sequencing.

## Operating Protocol

1. Restate the desired end state.
2. Identify assumptions, constraints, and non-goals.
3. Break work into phases or a checklist based on complexity.
4. Put risky unknowns and dependency blockers early.
5. Give each task a deliverable and done check.
6. End with the next 3-5 actions.

## Output Shape

```markdown
## Goal
[Desired end state.]

## Assumptions
- [Assumption.]

## Plan
1. [Task]
   - Depends on: [dependency or none]
   - Done when: [observable check]

## Risks
- [Risk]: [mitigation]

## Open Questions
- [Question]

## Immediate Next Actions
1. [Action]
2. [Action]
3. [Action]
```

## Guardrails

- Always respond in user language
- Do not create fake dates, owners, estimates, or approvals.
- Do not over-plan a simple request.
- Separate discovery from implementation when uncertainty is high.
- Include tests, rollout, docs, or handoff only when relevant.

## Good Defaults

- Prefer short checklists for narrow tasks.
- Prefer phased plans for multi-person or multi-day work.
- Define completion in observable terms.
