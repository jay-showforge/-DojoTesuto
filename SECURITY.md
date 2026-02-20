# Security Policy

## Scope

DojoTesuto is a local test harness. It runs entirely on your machine.
It does not make network calls, fetch remote quests, or transmit any data.

## Design Constraints

- **YAML quests are data, not code.** Challenge files are never evaluated or executed.
- **No remote execution.** No built-in remote-fetch, download, or outbound network paths.
- **No obfuscated scripts.** All source is plain, readable Python.
- **Sandboxed file writes.** Forge mode may only write to `SOUL.md`, `patches/`, and `skills_generated/`. All paths are validated before write (see `runner.py:_is_safe_path`).
- **Reflection responses are validated.** Size limits and type checks are enforced before any patch is applied (see `runner.py:_validate_reflection_response`).
- **Provider keys stay local.** API keys are read from environment variables and never logged, stored, or transmitted by the harness itself.

## Reporting a Vulnerability

If you find a security issue in DojoTesuto (e.g. a path traversal in the sandbox,
an injection via quest YAML, or an unsafe eval path):

1. **Do not open a public GitHub issue.**
2. Open a [GitHub Security Advisory](https://github.com/jay-showforge/DojoTesuto/security/advisories/new)
   (private, visible only to maintainers).
3. Include a minimal reproduction — what input triggers the issue, what happens,
   and what you expected.

I aim to respond within **7 days** and to publish a fix within **30 days** of a confirmed issue.

## Out of Scope

- Issues in third-party provider SDKs (openai, anthropic, ollama) — report those upstream.
- Prompt injection against your own agent (that is the point of DojoTesuto, not a bug).
