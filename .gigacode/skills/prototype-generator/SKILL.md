---
name: prototype-generator
description: Generate a small local UI prototype when workspace editing is available, or produce a precise prototype specification when it is not; use for quick product validation with realistic mock data and clear scope.
---

# Prototype Generator

## Purpose

Use this skill when the user wants something concrete enough to inspect: a small coded prototype, a screen/flow specification, or a mock-data demo. The prototype is for validation, not production.

## Use For

- One-screen UI concepts.
- Short product flows.
- Internal tool or dashboard mockups.
- Interaction demos with local mock data.
- Prototype specs that another agent or engineer can implement.

## Operating Protocol

1. Define the single question the prototype should answer.
2. Pick the smallest useful artifact:
   - local code if editing is available and appropriate;
   - prototype spec if editing is unavailable, unsafe, or not requested.
3. Use existing workspace patterns and dependencies when coding.
4. Include only essential states: default, empty, loading, error, success, disabled, selected.
5. Keep fake data local and clearly marked.
6. Report files changed, how to view the prototype, and what is out of scope.

## Output Shape

For a coded prototype:

```markdown
Built in:
- [file/path]

What it shows:
- [primary flow]
- [included states]

How to view:
- [valid local command or file path]

Mocked:
- [fake data/actions]
```

For a spec:

```markdown
## Prototype Scope
[What the prototype should prove.]

## Flow
1. [Step]
2. [Step]

## Screens And States
- [Screen/state]: [layout, content, controls, behavior.]

## Mock Data
- [Field]: [sample value]

## Acceptance Checks
- [Observable behavior.]
```

## Guardrails

- Always respond in user language
- Do not build a full product or marketing landing page unless asked.
- Do not add backends, auth, databases, payment flows, or external services unless explicitly requested.
- Do not claim the prototype is production-ready.
- Verify visually or by running only when the environment and request allow it.

## Good Defaults

- One primary flow beats many shallow screens.
- Use realistic content instead of lorem ipsum.
- Prefer clear hierarchy and usable controls over decoration.
