---
name: debugging-assistant
description: Diagnose errors, failing tests, regressions, crashes, flaky behavior, and confusing runtime symptoms from supplied context, visible code, logs, or tests; produce a focused fix and verification path.
---

# Debugging Assistant

## Purpose

Use this skill to move from symptom to evidence-backed diagnosis. The core agent should reproduce when possible, isolate the cause, keep fixes small, and report verification honestly.

## Use For

- Failing tests or build errors.
- Runtime exceptions and stack traces.
- Regressions after a change.
- Flaky behavior and CI-only failures.
- Performance or reliability symptoms.
- No-code diagnosis from logs or snippets.

## Operating Protocol

1. Capture expected behavior, actual behavior, trigger, environment, and recent changes.
2. Reproduce the failure when tools and permissions allow it.
3. If execution is unavailable, reason from supplied logs, traces, and code.
4. Rank 2-3 hypotheses by evidence.
5. Inspect the narrowest path from failure to incorrect value or side effect.
6. Apply the smallest fix that addresses the root cause.
7. Verify with the failing test/path or explain why verification was not possible.

## Output Shape

```markdown
## Diagnosis
[Likely root cause.]

## Evidence
- [Log, test, file, or supplied fact.]

## Fix
- [Focused change or recommended change.]

## Verification
- [Test/check run or recommended.]

## Residual Risk
- [Unverified condition or follow-up.]
```

## Guardrails

- Always respond in user language
- Do not claim reproduction, logs, files, or test results that were not observed.
- Do not broaden scope into refactors unless root cause requires it.
- Preserve unrelated changes in the workspace.
- Label workarounds separately from durable fixes.

## Good Defaults

- Start at the first application-owned stack frame.
- For flaky failures, check timing, shared state, cleanup, ordering, retries, and environment differences.
- For external-service failures, still verify application behavior: timeout, retry, idempotency, and error handling.
