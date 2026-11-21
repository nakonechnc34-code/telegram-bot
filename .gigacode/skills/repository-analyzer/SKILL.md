---
name: repository-analyzer
description: Analyze available repository files to explain architecture, stack, entry points, module boundaries, workflows, risks, and implementation-relevant context without making unsupported claims.
---

# Repository Analyzer

## Purpose

Use this skill before changing, reviewing, or explaining an unfamiliar codebase. The core agent should build a grounded map from visible repository evidence, not generic framework assumptions.

## Use For

- Onboarding to a repository.
- Finding where a feature belongs.
- Understanding build, test, and runtime flow.
- Mapping modules, packages, entry points, and boundaries.
- Risk assessment before implementation.
- Planning a change with likely files and verification steps.

## Operating Protocol

1. Clarify the analysis goal: overview, implementation recon, risk scan, migration, testing, or onboarding.
2. Inspect primary evidence when available: manifests, lockfiles, configs, CI, docs, entry points, source, tests, migrations.
3. Identify stack, app type, package/workspace model, and runtime entry points.
4. Trace representative flows only as deep as needed for the user's task.
5. Separate confirmed facts from likely inferences.
6. End with useful next files, risks, or change points.

## Output Shape

```markdown
## What This Repo Is
[Short description grounded in files.]

## Stack And Workflows
- [Runtime/tool]: [evidence.]

## Structure
- `[path]`: [purpose.]

## Main Flows
- [entry -> module -> output.]

## Relevant Risks
- [Risk]: [evidence and impact.]

## Next Files To Read / Change
- `[path]`: [why.]
```

For implementation recon:

```markdown
## Relevant Areas
- `[path]`: [why it matters.]

## Existing Pattern
[How similar behavior works.]

## Likely Change Points
- `[path]`: [expected change.]

## Verification Plan
- [Focused test or manual check.]
```

## Guardrails

- Always respond in user language
- Do not claim files, branches, services, commands, or runtime behavior that were not inspected.
- Do not edit files unless the user asks for implementation.
- Treat framework conventions as likely until repository code confirms them.
- If README and executable config disagree, report the conflict.

## Good Defaults

- Cite file paths and line references when available.
- Prefer repository-specific patterns over generic architecture advice.
