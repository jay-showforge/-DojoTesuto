# DojoTesuto Quest Schema

Required top-level fields:
- `id`          — unique quest identifier (kebab-case)
- `tier`        — difficulty tier (squire, knight, master)
- `category`    — failure mode category (safety, reliability, memory, tooling, cost)
- `description` — one-line human-readable description
- `mock`        — true/false, whether this quest uses mocked inputs
- `budget`      — resource limits (see below)
- `primary`     — primary challenge definition
- `variants`    — list of variant challenge definitions (at least one required)

## Budget Fields
- `max_steps`   — max number of steps before budget exceeded
- `max_seconds` — max wall-clock seconds before budget exceeded
- `max_tokens`  — max estimated tokens in agent response before budget exceeded

## Challenge Definition Fields (primary and each variant)
- `steps`       — ordered list of steps
- `assertions`  — list of pass/fail checks against context

## Step Types
- `simulate_timeout`  — payload: `{ seconds: N }`
- `inject_text`       — payload: `{ source: "...", text: "..." }`
- `bad_tool_args`     — payload: `{ tool_name: "...", args: {} }`
- `set_fact`          — payload: `{ key: "...", value: "..." }`
- `ask`               — payload: `{ question: "..." }` — prompts agent for response

## Assertion Types
- `must_contain`      — payload: `{ field: response, text: "..." }`
- `must_not_contain`  — payload: `{ field: response, text: "..." }`
- `must_equal`        — payload: `{ key: "...", value: "..." }` or `{ field: response, value: "..." }`
- `budget_ok`         — passes if all budget limits were respected

## Variant Design Guideline
Variants must test the same underlying concept as the primary, using different surface details
(different tool names, different injected text, different phrasing). A patch that only handles
the primary scenario must fail the variant. This enforces genuine generalization.

## Optional Quest Fields

- `reflection_hint` — A plain-text hint for the reflection LLM describing the failure class
  and what a strong, generalizable guardrail looks like for this quest. This is injected
  into the Reflection Request so the LLM has precise guidance rather than guessing.

  Example:
  ```
  reflection_hint: >
    The failure class is: agent does not enforce retry limits.
    A strong guardrail must specify a concrete limit, a stop condition,
    and an escalation path. It must apply to ANY repeated tool failure.
  ```
