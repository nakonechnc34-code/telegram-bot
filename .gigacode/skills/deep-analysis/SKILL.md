---
name: deep-analysis
description: Analyze ambiguous questions, plans, decisions, and documents using available conversation and workspace context; produce evidence, assumptions, tradeoffs, risks, and actionable recommendations without inventing unavailable facts.
---

# Deep Analysis

## Purpose

Use this skill when the user needs a rigorous answer rather than a fast reaction. The goal is to help the core agent reason clearly from the context it actually has: user-provided text, visible files, prior conversation, and explicitly stated assumptions.

## Use For

- Decision memos and second opinions.
- Tradeoff analysis between options.
- Risk review of plans, proposals, specs, or strategies.
- Critical review of arguments or documents.
- Turning scattered reasoning into an actionable recommendation.

## Operating Protocol

1. State the exact question or decision being answered.
2. Separate facts, assumptions, inferences, and unknowns.
3. Identify the few variables that drive the outcome.
4. Compare options against the same criteria when alternatives exist.
5. Surface failure modes, hidden costs, and reversibility.
6. Give a recommendation, confidence level, and next step.

## Output Shape

```markdown
## Bottom Line
[Direct conclusion in 1-3 sentences.]

## Evidence
- [Fact or supplied context.]
- [Fact or supplied context.]

## Assumptions
- [Assumption that affects confidence.]

## Tradeoffs
- [Option]: [upside, downside, best use case.]

## Risks
- [Risk]: [impact and mitigation.]

## Recommendation
[What to do next and why.]
```

## Guardrails

- Always respond in user language
- Do not imply access to external research, private data, hidden files, tables, or transcripts.
- Ask at most a few clarifying questions only when the answer would materially change.
- If evidence is thin, provide a bounded hypothesis instead of a definitive answer.
- For legal, medical, financial, safety, or compliance topics, keep advice non-professional and recommend expert review where appropriate.

## Good Defaults

- Lead with the answer.
- Keep the structure proportional to stakes.
- Use plain language over impressive framing.
- Say what would change the recommendation.
