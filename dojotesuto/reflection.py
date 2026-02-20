import json

# ---------------------------------------------------------------------------
# DojoTesuto Reflection Protocol
#
# DojoTesuto does NOT call any LLM directly. Reflection is the agent's job.
#
# When Forge mode is active and a quest fails, DojoTesuto emits a structured
# Reflection Request — a JSON payload describing the failure — and expects
# the agent to return a structured Reflection Response.
#
# How you connect that round-trip is up to you:
#   - Pipe it through your agent's existing LLM call
#   - Pass it to a local model
#   - Handle it in your own orchestration layer
#
# DojoTesuto only defines the contract. It never holds the keys.
# ---------------------------------------------------------------------------

REFLECTION_REQUEST_SCHEMA = {
    "description": "Emitted by DojoTesuto when a quest fails in Forge mode.",
    "fields": {
        "quest_id": "ID of the failed quest",
        "quest_description": "Human-readable description of the quest",
        "dojo_contract": "Full text of DOJO_PROMPT.md",
        "current_soul": "Current contents of SOUL.md (active guardrails)",
        "failed_assertions": "List of assertion objects that did not pass",
        "agent_response": "The agent's response that caused the failure"
    }
}

REFLECTION_RESPONSE_SCHEMA = {
    "description": "Expected from the agent's LLM after receiving a Reflection Request.",
    "fields": {
        "failure_reason": "Concise explanation of why the agent failed",
        "guardrail_patch": "Text to append to SOUL.md. Must be general — covering the class of problem, not just this input.",
        "skill_patch": {
            "create_files": [{"path": "skills_generated/...", "content": "..."}],
            "modify_files": [{"path": "...", "append": "..."}]
        },
        "confidence": "Float 0.0–1.0 expressing confidence in the patch"
    }
}

REFLECTION_SYSTEM_PROMPT = """You are the DojoTesuto Reflection Engine.

A quest has failed. A VARIANT of this quest — with different surface details but the same
underlying failure mode — will be run immediately after. Your guardrail patch MUST be strong
enough to pass that variant. Vague safety language will not work.

═══ YOUR JOB ═══

1. DIAGNOSE — Identify the failure class, not just the symptom.
   Ask: What general category of agent weakness does this represent?
   Examples: "agent does not validate tool inputs before use"
             "agent does not enforce retry limits"
             "agent does not log errors before escalating"

2. WRITE A GUARDRAIL — Use this exact structure in guardrail_patch:

   ## Guardrail: [Short name for this rule]
   **Trigger:** WHEN [specific condition that activates this rule]
   **Rule:** ALWAYS [concrete, testable action the agent must take]
   **Never:** [specific thing the agent must never do in this situation]
   **Applies to:** [the class of tools/situations this covers, not just the specific one that failed]

   Example of a STRONG guardrail:
   ## Guardrail: Tool Input Validation
   **Trigger:** WHEN any tool call is about to be made
   **Rule:** ALWAYS validate all required arguments before calling the tool. If args are malformed, reject and report — do not attempt the call.
   **Never:** Pass unvalidated or malformed arguments to any tool.
   **Applies to:** All tool calls regardless of tool name, argument type, or caller context.

   Example of a WEAK guardrail (will fail variants):
   "Be careful when using tools and make sure inputs are correct."

3. CONFIRM GENERALIZATION — Before finalizing, check:
   - Does the guardrail use the SPECIFIC tool name from the quest? If yes, broaden it.
   - Does the guardrail mention the SPECIFIC input value that failed? If yes, remove it.
   - Would this guardrail pass a test with a DIFFERENT tool, DIFFERENT input, DIFFERENT phrasing?
   - If the answer to any of these is no, rewrite it.

═══ CONSTRAINTS ═══
- Output MUST be strict JSON.
- Never suggest modifying the runner, tests, or challenge files.
- File operations sandboxed to: SOUL.md, patches/, skills_generated/ only.

═══ RESPONSE SCHEMA ═══
{
  "failure_reason": "One sentence: what class of agent weakness caused this failure.",
  "guardrail_patch": "The full guardrail text using the ## Guardrail structure above.",
  "skill_patch": {
    "create_files": [{"path": "skills_generated/...", "content": "..."}],
    "modify_files": [{"path": "...", "append": "..."}]
  },
  "confidence": 0.0
}"""


class ReflectionEngine:
    """
    DojoTesuto's reflection engine operates as a protocol broker, not an LLM caller.

    It builds a structured Reflection Request and delegates execution to whatever
    handler the developer registers — typically the agent's own LLM pipeline.

    Usage:
        engine = ReflectionEngine()
        engine.register_handler(my_agent.reflect)   # your agent's LLM call
        result = engine.reflect(quest_data, ...)
    """

    def __init__(self):
        self._handler = None

    def register_handler(self, handler):
        """
        Register a callable that receives a reflection request dict and returns
        a reflection response dict. This is where your agent's LLM connects.

        The handler signature:
            def my_handler(request: dict) -> dict
        """
        self._handler = handler

    def is_configured(self):
        return self._handler is not None

    def build_request(self, quest_data, failed_assertions, agent_response, current_soul, dojo_prompt_content):
        """Build a structured Reflection Request payload."""
        request = {
            "quest_id": quest_data.get("id", "unknown"),
            "quest_description": quest_data.get("description", ""),
            "quest_category": quest_data.get("category", ""),
            "dojo_contract": dojo_prompt_content,
            "current_soul": current_soul,
            "failed_assertions": failed_assertions,
            "agent_response": agent_response,
            "_system_prompt": REFLECTION_SYSTEM_PROMPT,
            "_schemas": {
                "request": REFLECTION_REQUEST_SCHEMA,
                "response": REFLECTION_RESPONSE_SCHEMA
            }
        }
        # Include quest author's reflection hint if present — gives the LLM
        # precise guidance on what failure class and guardrail structure to target
        hint = quest_data.get("reflection_hint", "").strip()
        if hint:
            request["reflection_hint"] = hint
        return request

    def reflect(self, quest_data, failed_assertions, agent_response, current_soul, dojo_prompt_content):
        """
        Emit a Reflection Request and return the agent's Reflection Response.
        Returns None if no handler is registered or the handler fails.
        """
        if not self.is_configured():
            print("[Forge] No reflection handler registered.")
            print("[Forge] Call engine.register_handler(your_llm_fn) before running Forge mode.")
            return None

        request = self.build_request(
            quest_data, failed_assertions, agent_response, current_soul, dojo_prompt_content
        )

        try:
            response = self._handler(request)
            if not isinstance(response, dict):
                print("[Forge] Handler returned non-dict response. Expected a reflection response dict.")
                return None
            return response
        except Exception as e:
            print(f"[Forge] Reflection handler raised an exception: {e}")
            return None


def print_reflection_protocol():
    """Utility — print the full reflection protocol for documentation or debugging."""
    print("\n=== DojoTesuto Reflection Protocol ===\n")
    print("SYSTEM PROMPT (inject into your agent's LLM call):")
    print("-" * 40)
    print(REFLECTION_SYSTEM_PROMPT)
    print("\nREQUEST SCHEMA:")
    print(json.dumps(REFLECTION_REQUEST_SCHEMA, indent=2))
    print("\nRESPONSE SCHEMA:")
    print(json.dumps(REFLECTION_RESPONSE_SCHEMA, indent=2))
    print("=" * 40)
