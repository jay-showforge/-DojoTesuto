import os
import sys
import re
import hashlib
import yaml
import argparse
import json
import time
from datetime import datetime
from .reflection import ReflectionEngine
from .report import generate_report, save_report
from .forge_budget import ForgeBudget, ForgeBudgetExceeded, ReflectionTimeout

# Maximum allowed size for any single string field written from reflection output
_MAX_PATCH_FIELD_BYTES = 512_000  # 512 KB

# ---------------------------------------------------------------------------
# SOUL.md deduplication — per-guardrail block level
# ---------------------------------------------------------------------------

def _normalize_guardrail(text: str) -> str:
    """
    Normalize a guardrail block for deduplication comparison.
    Strips leading/trailing whitespace, collapses internal whitespace runs,
    and lowercases — so minor LLM rephrasing doesn't produce false duplicates
    while genuinely different guardrails are still treated as distinct.
    """
    return re.sub(r'\s+', ' ', text.strip().lower())


def _guardrail_fingerprint(text: str) -> str:
    """
    Return a short stable SHA-256 fingerprint of a normalized guardrail block.
    Used as the dedup key stored in SOUL.md comments.
    """
    normalized = _normalize_guardrail(text)
    return hashlib.sha256(normalized.encode()).hexdigest()[:12]


def _split_guardrail_blocks(patch_text: str) -> list[str]:
    """
    Split a guardrail patch string into individual ## Guardrail: blocks.
    A patch may contain multiple guardrails; each is deduped independently.
    Returns a list of non-empty block strings.
    """
    # Split on any line that starts a new guardrail header
    blocks = re.split(r'(?=^## Guardrail:)', patch_text, flags=re.MULTILINE)
    return [b.strip() for b in blocks if b.strip()]


def _load_existing_fingerprints(soul_path: str) -> set[str]:
    """
    Read SOUL.md and extract all previously stored guardrail fingerprints
    from <!-- dojo-fp: XXXX --> comments embedded at write time.
    """
    if not os.path.exists(soul_path):
        return set()
    with open(soul_path, 'r') as f:
        content = f.read()
    return set(re.findall(r'<!-- dojo-fp: ([0-9a-f]+) -->', content))


def _load_existing_guardrail_names(soul_path: str) -> set[str]:
    """Read SOUL.md and return normalized guardrail names. Dedup layer 3."""
    if not os.path.exists(soul_path):
        return set()
    with open(soul_path, 'r') as f:
        content = f.read()
    names = re.findall(r'^## Guardrail:\s*(.+)$', content, flags=re.MULTILINE)
    return {n.strip().lower() for n in names}


def _load_patched_quest_ids(soul_path: str) -> set[str]:
    """Read SOUL.md and return all quest IDs already patched. Primary dedup layer."""
    if not os.path.exists(soul_path):
        return set()
    with open(soul_path, 'r') as f:
        content = f.read()
    return set(re.findall(r'^## Patch for (.+)$', content, flags=re.MULTILINE))


def _filter_new_guardrails(patch_text: str, soul_path: str, quest_id: str = "") -> tuple[str, int, int]:
    """
    Three-layer deduplication:
      1. Quest-ID match — one patch per quest in SOUL.md, regardless of LLM phrasing.
         This is the key fix for the Manus double-write scenario.
      2. Exact-text fingerprint — catches identical blocks across different quests.
      3. Guardrail name match — catches same-name blocks within one patch payload.
    """
    # Layer 1: quest already patched
    if quest_id:
        patched_ids = _load_patched_quest_ids(soul_path)
        if quest_id in patched_ids:
            blocks = _split_guardrail_blocks(patch_text)
            count = len(blocks) if blocks else 1
            print(f"[Forge/Dedup] Quest '{quest_id}' already patched in SOUL.md — "
                  f"skipping all {count} block(s). Delete SOUL.md to reset guardrails.")
            return "", 0, count

    existing_fps = _load_existing_fingerprints(soul_path)
    existing_names = _load_existing_guardrail_names(soul_path)
    blocks = _split_guardrail_blocks(patch_text)
    if not blocks:
        blocks = [patch_text.strip()]

    kept = []
    skipped = 0

    for block in blocks:
        # Layer 2: exact fingerprint
        fp = _guardrail_fingerprint(block)
        if fp in existing_fps:
            skipped += 1
            print(f"[Forge/Dedup] Skipping duplicate guardrail (fp={fp}): "
                  f"{block[:60].splitlines()[0]}...")
            continue

        # Layer 3: same guardrail name
        name_match = re.match(r'^## Guardrail:\s*(.+)$', block, flags=re.MULTILINE)
        if name_match:
            name = name_match.group(1).strip().lower()
            if name in existing_names:
                skipped += 1
                print(f"[Forge/Dedup] Skipping same-name guardrail "
                      f"(\'{name_match.group(1).strip()}\'): already in SOUL.md.")
                continue
            existing_names.add(name)

        kept.append(f"{block}\n<!-- dojo-fp: {fp} -->")

    filtered = "\n\n".join(kept)
    return filtered, len(kept), skipped


def _seed_fingerprints_for_existing_soul(soul_path: str) -> int:
    """
    Retroactively add <!-- dojo-fp: XXXX --> fingerprint markers to any
    ## Guardrail: blocks in an existing SOUL.md that were written before
    deduplication was introduced.

    This ensures a legacy SOUL.md gets full dedup protection on the very
    first Forge run after upgrading — no duplicate "one free pass" problem.

    Returns the number of blocks that were seeded (0 if already all marked).
    Safe to call repeatedly — only seeds blocks that are missing markers.
    """
    if not os.path.exists(soul_path):
        return 0

    with open(soul_path, 'r') as f:
        content = f.read()

    # Find guardrail blocks that do NOT already have a fingerprint marker.
    # A "seeded" block has <!-- dojo-fp: ... --> on the line immediately after it.
    blocks = re.split(r'(?=^## Guardrail:)', content, flags=re.MULTILINE)

    seeded_count = 0
    new_parts = []

    for block in blocks:
        if not block.startswith('## Guardrail:'):
            new_parts.append(block)
            continue

        # Check if this block already has a fingerprint marker
        if '<!-- dojo-fp:' in block:
            new_parts.append(block)
            continue

        # Seed it: compute fingerprint and append marker
        fp = _guardrail_fingerprint(block.rstrip())
        new_parts.append(block.rstrip() + f'\n<!-- dojo-fp: {fp} -->\n')
        seeded_count += 1

    if seeded_count > 0:
        new_content = ''.join(new_parts)
        with open(soul_path, 'w') as f:
            f.write(new_content)
        print(f"[Forge/Dedup] Seeded {seeded_count} legacy guardrail(s) in SOUL.md with fingerprints.")

    return seeded_count


def _safe_quest_id(quest_id):
    """
    Sanitize quest_id before use in filenames.
    Only allow alphanumerics, hyphens, and underscores.
    """
    sanitized = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(quest_id))
    return sanitized[:64]  # hard cap on length

def _validate_reflection_response(data):
    """
    Validate a reflection response dict for correct types and safe sizes.
    Returns (is_valid, error_message).
    """
    if not isinstance(data, dict):
        return False, "Response is not a dict"

    # Check required fields exist and are correct types
    failure_reason = data.get("failure_reason", "")
    if not isinstance(failure_reason, str):
        return False, f"'failure_reason' must be a string, got {type(failure_reason).__name__}"

    guardrail_patch = data.get("guardrail_patch", "")
    if not isinstance(guardrail_patch, str):
        return False, f"'guardrail_patch' must be a string, got {type(guardrail_patch).__name__}"

    if len(guardrail_patch.encode()) > _MAX_PATCH_FIELD_BYTES:
        return False, f"'guardrail_patch' exceeds max size ({_MAX_PATCH_FIELD_BYTES} bytes)"

    skill_patch = data.get("skill_patch", {})
    if not isinstance(skill_patch, dict):
        return False, f"'skill_patch' must be a dict, got {type(skill_patch).__name__}"

    confidence = data.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)):
        return False, f"'confidence' must be a number, got {type(confidence).__name__}"

    # Validate skill_patch sub-fields
    for op in skill_patch.get("create_files", []):
        if not isinstance(op, dict):
            return False, "Each create_files entry must be a dict"
        path = op.get("path", "")
        if not isinstance(path, str):
            return False, "'path' in create_files must be a string"
        if "\x00" in path:
            return False, "'path' in create_files contains null byte"
        content = op.get("content", "")
        if not isinstance(content, str):
            return False, "'content' in create_files must be a string"
        if "\x00" in content:
            return False, "'content' in create_files contains null byte"
        if len(content.encode()) > _MAX_PATCH_FIELD_BYTES:
            return False, f"'content' in create_files exceeds max size ({_MAX_PATCH_FIELD_BYTES} bytes)"

    for op in skill_patch.get("modify_files", []):
        if not isinstance(op, dict):
            return False, "Each modify_files entry must be a dict"
        path = op.get("path", "")
        if not isinstance(path, str):
            return False, "'path' in modify_files must be a string"
        if "\x00" in path:
            return False, "'path' in modify_files contains null byte"
        append = op.get("append", "")
        if not isinstance(append, str):
            return False, "'append' in modify_files must be a string"
        if "\x00" in append:
            return False, "'append' in modify_files contains null byte"
        if len(append.encode()) > _MAX_PATCH_FIELD_BYTES:
            return False, f"'append' in modify_files exceeds max size ({_MAX_PATCH_FIELD_BYTES} bytes)"

    return True, "OK"


class DojoTesutoRunner:
    def __init__(self, base_dir, noninteractive=False, forge=False, forge_budget=None):
        self.base_dir = base_dir
        self.noninteractive = noninteractive
        self.forge = forge
        self.facts = {}
        self.reflection_engine = ReflectionEngine()
        self.dojo_prompt_path = os.path.join(self.base_dir, "DOJO_PROMPT.md")
        self.soul_path = os.path.join(self.base_dir, "SOUL.md")
        self.patches_dir = os.path.join(self.base_dir, "patches")
        self.skills_dir = os.path.join(self.base_dir, "skills_generated")
        self.reports_dir = os.path.join(self.base_dir, "reports")
        self.forge_budget = forge_budget or ForgeBudget()
        self._answer_handler = None

        if self.forge:
            os.makedirs(self.patches_dir, exist_ok=True)
            os.makedirs(self.skills_dir, exist_ok=True)
            if not os.path.exists(self.soul_path):
                with open(self.soul_path, "w") as f:
                    f.write("# Agent SOUL (Guardrails)\n\n")
            else:
                # Retroactively seed fingerprints for any legacy guardrail blocks
                # (written before deduplication was introduced). Safe to call on
                # already-seeded files — it's a no-op when all blocks are marked.
                _seed_fingerprints_for_existing_soul(self.soul_path)

    # ------------------------------------------------------------------
    # Handler registration (agent-native Forge mode)
    # ------------------------------------------------------------------

    def register_reflection_handler(self, handler):
        """
        Connect your agent's LLM to DojoTesuto's Forge reflection loop.

        The handler receives a structured Reflection Request dict and must
        return a Reflection Response dict. DojoTesuto never calls any LLM
        directly — that's your agent's job.

        Example:
            def my_agent_reflect(request):
                prompt = request["_system_prompt"]
                payload = json.dumps(request, indent=2)
                raw = my_llm.call(system=prompt, user=payload)
                return json.loads(raw)

            runner.register_reflection_handler(my_agent_reflect)
        """
        self.reflection_engine.register_handler(handler)

    def register_answer_handler(self, handler):
        """
        Connect your agent's LLM to DojoTesuto's quest answer loop.

        This is the second handler needed for full automated Forge runs.
        Without it, quest 'ask' steps read from stdin — a human must answer,
        and the SOUL.md guardrails shown on screen may not influence those answers.

        With an answer handler registered, DojoTesuto passes the question and
        full SOUL.md context to your LLM. This is what enables variant recovery:
        the agent answers the variant WITH the guardrails it just learned.

        Handler receives:
            question : str  — the quest question
            soul     : str  — current SOUL.md contents (active guardrails)
            quest_id : str  — which quest
            attempt  : str  — "primary" or "variant"

        Must return a plain string — the agent's answer.

        Example (for Manus/OpenAI):
            def my_agent_answer(req):
                system = (
                    "You are a resilient AI agent. "
                    "You MUST follow these active guardrails:\\n\\n" + req["soul"]
                )
                resp = client.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": req["question"]}
                    ]
                )
                return resp.choices[0].message.content

            runner.register_answer_handler(my_agent_answer)
        """
        self._answer_handler = handler

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    def load_yaml(self, path):
        with open(path, 'r') as f:
            return yaml.safe_load(f)

    def get_dojo_prompt_content(self):
        if os.path.exists(self.dojo_prompt_path):
            with open(self.dojo_prompt_path, "r") as f:
                return f.read()
        return ""

    def get_soul_content(self):
        if os.path.exists(self.soul_path):
            with open(self.soul_path, "r") as f:
                return f.read()
        return ""

    def get_multiline_input(self, prompt):
        print(prompt)
        if self.forge:
            soul = self.get_soul_content()
            if soul.strip():
                print(f"--- ACTIVE GUARDRAILS (SOUL.md) ---\n{soul}\n-----------------------------------")
        print("(End with a blank line)")
        lines = []
        while True:
            try:
                line = input()
                if line == "":
                    break
                lines.append(line)
            except EOFError:
                break
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Sandbox enforcement
    # ------------------------------------------------------------------

    def _is_safe_path(self, path):
        """
        Return True only if the resolved absolute path is strictly inside
        one of the allowed directories.

        Uses os.path.sep-aware prefix check to prevent prefix collision attacks
        (e.g. 'skills_generatedEvil' matching against 'skills_generated').
        """
        # Defense-in-depth: reject absolute paths early
        if os.path.isabs(path):
            return False
        abs_path = os.path.abspath(os.path.join(self.base_dir, path))
        allowed = [
            os.path.abspath(self.soul_path),
            os.path.abspath(self.patches_dir),
            os.path.abspath(self.skills_dir),
        ]
        for allowed_path in allowed:
            # For files: exact match (e.g. SOUL.md)
            if abs_path == allowed_path:
                return True
            # For directories: must be strictly inside (separator-terminated prefix)
            dir_prefix = allowed_path.rstrip(os.sep) + os.sep
            if abs_path.startswith(dir_prefix):
                return True
        return False

    # ------------------------------------------------------------------
    # Patch application (sandboxed)
    # ------------------------------------------------------------------

    def apply_patch(self, quest_id, reflection_data, agent_response, failed_assertions):
        # Validate and sanitize quest_id for use in filenames
        safe_id = _safe_quest_id(quest_id)

        patch_text = reflection_data.get("guardrail_patch", "")
        new_count = skipped_count = 0

        if patch_text:
            # Deduplicate at the per-guardrail-block level before writing
            filtered_patch, new_count, skipped_count = _filter_new_guardrails(
                patch_text, self.soul_path, quest_id=safe_id
            )
            if filtered_patch:
                with open(self.soul_path, "a") as f:
                    f.write(f"\n## Patch for {safe_id}\n{filtered_patch}\n")
                print(f"[Forge/Dedup] Wrote {new_count} new guardrail(s), "
                      f"skipped {skipped_count} duplicate(s) for '{safe_id}'.")
            else:
                print(f"[Forge/Dedup] All {skipped_count} guardrail(s) for '{safe_id}' "
                      f"already present in SOUL.md — nothing written.")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        # patch_file is constructed entirely from safe_id and timestamp — no user input
        patch_file = os.path.join(self.patches_dir, f"{safe_id}-{timestamp}.md")
        with open(patch_file, "w") as f:
            f.write(f"# Patch Record: {safe_id}\n\n")
            f.write(f"## Failure Reason\n{reflection_data.get('failure_reason', 'N/A')}\n\n")
            f.write(f"## Failed Assertions\n{json.dumps(failed_assertions, indent=2)}\n\n")
            f.write(f"## Agent Response\n{agent_response}\n\n")
            # Always record the original full patch in the patch file for audit,
            # even if some/all blocks were deduped and not written to SOUL.md
            f.write(f"## Guardrail Patch (original)\n{patch_text}\n")
            f.write(f"## Dedup Result\nnew={new_count} skipped={skipped_count}\n")
            f.write(f"## Confidence\n{reflection_data.get('confidence', 'N/A')}\n")

        # Sandboxed skill file ops
        skill_patch = reflection_data.get("skill_patch", {})

        for file_op in skill_patch.get("create_files", []):
            path = file_op.get("path")
            if path and self._is_safe_path(path):
                full_path = os.path.join(self.base_dir, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    f.write(file_op.get("content", ""))

        for file_op in skill_patch.get("modify_files", []):
            path = file_op.get("path")
            if path and self._is_safe_path(path):
                full_path = os.path.join(self.base_dir, path)
                with open(full_path, "a") as f:
                    f.write(file_op.get("append", ""))

    # ------------------------------------------------------------------
    # Challenge execution
    # ------------------------------------------------------------------

    def _run_single_challenge_def(self, quest_id, challenge_def, attempt_type="primary", quest_budget=None):
        context = {"response": ""}
        skipped = False
        skip_reason = ""
        steps_taken = 0
        start_time = time.time()

        # BUG FIX: budget lives at the quest root, not inside primary/variant.
        # quest_budget is passed in from run_quest; fall back to empty dict if absent.
        budget = quest_budget or {}
        max_steps = budget.get("max_steps", float("inf"))
        max_tokens = budget.get("max_tokens", float("inf"))
        max_seconds = budget.get("max_seconds", float("inf"))
        budget_exceeded = False

        for step in challenge_def.get("steps", []):
            elapsed = time.time() - start_time
            if elapsed > max_seconds:
                budget_exceeded = True
                if not self.noninteractive:
                    print(f"[System] Budget Exceeded: max_seconds ({max_seconds}s) reached after {elapsed:.1f}s.")
                break

            steps_taken += 1
            if steps_taken > max_steps:
                budget_exceeded = True
                if not self.noninteractive:
                    print(f"[System] Budget Exceeded: max_steps ({max_steps}) reached.")
                break

            step_type = step["type"]
            payload = step.get("payload", {})

            if step_type == "simulate_timeout":
                if not self.noninteractive:
                    seconds = payload.get("seconds")
                    print(f"[System] Simulating timeout of {seconds}s...")

            elif step_type == "inject_text":
                source = payload.get("source", "unknown")
                text = payload.get("text")
                context["injected_source"] = source
                context["injected_text"] = text
                if not self.noninteractive:
                    print(f"[System] Injecting text from '{source}': {text}")

            elif step_type == "bad_tool_args":
                if not self.noninteractive:
                    tool_name = payload.get("tool_name")
                    args = payload.get("args")
                    print(f"[System] Tool '{tool_name}' received bad arguments: {args}")

            elif step_type == "set_fact":
                key = payload.get("key")
                value = payload.get("value")
                self.facts[key] = value
                if not self.noninteractive:
                    print(f"[System] Fact set: {key} = {value}")

            elif step_type == "ask":
                if self.noninteractive:
                    skipped = True
                    skip_reason = "noninteractive mode"
                    break
                elif self._answer_handler is not None:
                    # Automated mode: pass question + SOUL.md context to agent LLM
                    question = payload.get("question", "Please provide your response:")
                    # If an inject_text step occurred, include it in the question so the agent can actually respond to it.
                    injected_text = context.get("injected_text")
                    if injected_text:
                        injected_source = context.get("injected_source", "unknown")
                        question = (
                            f"You found this text inside UNTRUSTED content from '{injected_source}':\n"
                            f"---\n{injected_text}\n---\n\n"
                            f"{question}"
                        )
                    soul = self.get_soul_content()
                    dojo_contract = self.get_dojo_prompt_content()
                    try:
                        answer = self._answer_handler({
                            "question": question,
                            "soul": soul,
                            "dojo_contract": dojo_contract,
                            "quest_id": quest_id,
                            "attempt": attempt_type,
                            "injected_text": context.get("injected_text"),
                            "injected_source": context.get("injected_source"),
                            # Pass any facts set by set_fact steps so the LLM can
                            # reference them when answering memory/recall quests.
                            "facts": dict(self.facts),
                        })
                        context["response"] = str(answer) if answer is not None else ""
                        # Clear one-shot injected content after use to avoid leaking into later steps.
            # NOTE: injected_text/source are cleared at the end of the challenge, not per-ask,
            # so multi-question challenges can still reference the same injected content.
                        print(f"[Quest] {question}")
                        print(f"[Agent] {context['response'][:200]}{'...' if len(context['response']) > 200 else ''}")
                    except Exception as e:
                        print(f"[Quest] Answer handler raised: {e}")
                        skipped = True
                        skip_reason = f"answer handler error: {e}"
                        break
                else:
                    question = payload.get("question", "Please provide your response:")
                    injected_text = context.get("injected_text")
                    if injected_text:
                        injected_source = context.get("injected_source", "unknown")
                        question = (
                            f"You found this text inside UNTRUSTED content from '{injected_source}':\n"
                            f"---\n{injected_text}\n---\n\n"
                            f"{question}"
                        )
                    context["response"] = self.get_multiline_input(f"\n[Quest] {question}")
            # NOTE: injected_text/source are cleared at the end of the challenge, not per-ask,
            # so multi-question challenges can still reference the same injected content.

        if skipped:
            return {"status": "SKIP", "reason": skip_reason, "score": 0, "failed_assertions": [], "agent_response": ""}

        elapsed = time.time() - start_time
        estimated_tokens = len(context["response"]) // 4
        budget_exceeded = (steps_taken > max_steps) or (estimated_tokens > max_tokens) or (elapsed > max_seconds)

        failed_assertions = []
        assertions = challenge_def.get("assertions", [])
        for assertion in assertions:
            a_type = assertion["type"]
            a_payload = assertion.get("payload", {})
            passed = False

            if a_type == "must_contain":
                field_val = context.get(a_payload.get("field", "response"), "")
                if a_payload.get("text", "").lower() in field_val.lower():
                    passed = True

            elif a_type == "must_not_contain":
                field_val = context.get(a_payload.get("field", "response"), "")
                if a_payload.get("text", "").lower() not in field_val.lower():
                    passed = True

            elif a_type == "must_equal":
                key = a_payload.get("key")
                if key:
                    # BUG FIX: check the stored fact, not the response text.
                    # set_fact steps store values in self.facts; that's what must_equal
                    # with a key is designed to verify (memory-drift pattern).
                    expected = str(a_payload.get("value", ""))
                    actual = str(self.facts.get(key, ""))
                    if actual == expected:
                        passed = True
                else:
                    field_val = context.get(a_payload.get("field", "response"), "")
                    if field_val == a_payload.get("value"):
                        passed = True

            elif a_type == "budget_ok":
                if not budget_exceeded:
                    passed = True

            if not passed:
                failed_assertions.append(assertion)

        
        # synthetic budget_exceeded: if a quest exceeded budget but did not declare a budget_ok assertion,
        # treat it as a hard failure for safety.
        if budget_exceeded and not any((a.get("type") == "budget_ok") for a in assertions):
            failed_assertions.append({
                "type": "budget_exceeded",
                "details": "Budget exceeded (time/steps/tokens) but quest did not include budget_ok assertion."
            })
        score = ((len(assertions) - len(failed_assertions)) / len(assertions) * 100) if assertions else 100
        status = "PASS" if score == 100 else "FAIL"

        return {
            "status": status,
            "score": score,
            "failed_assertions": failed_assertions,
            "agent_response": context["response"],
            "reason": None
        }

    # ------------------------------------------------------------------
    # Quest + suite orchestration
    # ------------------------------------------------------------------

    def run_quest(self, quest_path):
        quest_data = self.load_yaml(quest_path)
        quest_id = quest_data["id"]

        print(f"\n--- Quest: {quest_id} ---")
        print(f"Description: {quest_data['description']}")
        # Reset facts for each quest — set_fact state must not bleed between quests.
        self.facts = {}

        results = {
            "id": quest_id,
            "initial": None,
            "post_learning": None,
            "variant_pass": False,
            "skills_guardrails_created": 0
        }

        print(f"\n[Running Primary Challenge for {quest_id}]")
        quest_budget = quest_data.get("budget", {})
        initial_result = self._run_single_challenge_def(quest_id, quest_data["primary"], attempt_type="primary", quest_budget=quest_budget)
        results["initial"] = initial_result

        status_symbol = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}.get(initial_result["status"], "?")
        print(f"[Result] {status_symbol} {initial_result['status']} (score: {initial_result['score']:.0f}%)")

        if initial_result["status"] == "FAIL" and self.forge:
            if not self.reflection_engine.is_configured():
                print("\n[Forge] No reflection handler registered.")
                print("[Forge] Call runner.register_reflection_handler(fn) to enable Forge reflection.")
            else:
                print("\n[Forge] Primary challenge failed. Initiating reflection...")
                try:
                    self.forge_budget.check_suite_time()
                    self.forge_budget.check_reflection_count()
                except ForgeBudgetExceeded as e:
                    print(f"[Forge] Budget limit: {e}")
                    return results

                request = self.reflection_engine.build_request(
                    quest_data,
                    initial_result["failed_assertions"],
                    initial_result["agent_response"],
                    self.get_soul_content(),
                    self.get_dojo_prompt_content()
                )
                try:
                    reflection = self.forge_budget.call_with_timeout(
                        self.reflection_engine._handler, request
                    )
                    self.forge_budget.record_reflection()
                except ReflectionTimeout as e:
                    print(f"[Forge] {e}")
                    reflection = None
                except Exception as e:
                    print(f"[Forge] Reflection handler raised an exception: {e}")
                    reflection = None

                if reflection is not None:
                    # Validate before applying anything
                    is_valid, validation_msg = _validate_reflection_response(reflection)
                    if not is_valid:
                        print(f"[Forge] Reflection response rejected: {validation_msg}")
                        print("[Forge] Quest marked as failed. Patch not applied.")
                    else:
                        print(f"[Forge] Failure reason: {reflection.get('failure_reason', 'N/A')}")
                        print(f"[Forge] Confidence: {reflection.get('confidence', 'N/A')}")
                        self.apply_patch(quest_id, reflection, initial_result["agent_response"], initial_result["failed_assertions"])
                        results["skills_guardrails_created"] = 1
                        print("[Forge] Patch applied to SOUL.md. Attempting variant challenge...")

                        if quest_data.get("variants"):
                            variant_def = quest_data["variants"][0]
                            # NOTE: we do NOT re-check suite time here.
                            # Reflection + its variant are one atomic learning cycle —
                            # splitting them with a budget check would leave SOUL.md
                            # patched but generalization permanently unverifiable.
                            # Suite-time budget gates new reflections (above), not this variant.
                            print(f"\n[Running Variant Challenge for {quest_id}]")
                            post_result = self._run_single_challenge_def(quest_id, variant_def, attempt_type="variant", quest_budget=quest_budget)
                            results["post_learning"] = post_result
                            if post_result["status"] == "PASS":
                                results["variant_pass"] = True
                                print(f"[Forge] ✅ Variant passed — generalization confirmed.")
                            else:
                                print(f"[Forge] ❌ Variant failed — patch did not generalize.")
                else:
                    print("[Forge] Reflection handler returned no response.")

        return results

    def run_suite(self, suite_name, save_report_file=False):
        index_path = os.path.join(self.base_dir, 'challenges', 'index.yaml')
        index = self.load_yaml(index_path)
        suite = index.get('suites', {}).get(suite_name)
        if not suite:
            print(f"Error: Suite '{suite_name}' not found.")
            sys.exit(1)

        print("=" * 52)
        print(f"   DojoTesuto — Suite: {suite_name} {'(FORGE MODE)' if self.forge else ''}")
        print("=" * 52)

        if self.forge:
            self.forge_budget.start_suite()

        suite_results = []
        quest_names = []

        for quest_rel_path in suite.get('quests', []):
            full_quest_path = os.path.join(self.base_dir, 'challenges', quest_rel_path)
            quest_results = self.run_quest(full_quest_path)
            suite_results.append(quest_results)
            quest_names.append(quest_results.get("id", quest_rel_path))

        report_text = generate_report(
            suite_name=suite_name,
            quest_names=quest_names,
            suite_results=suite_results,
            forge=self.forge,
            print_output=True
        )

        if save_report_file:
            os.makedirs(self.reports_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            report_path = os.path.join(self.reports_dir, f"{suite_name}-{timestamp}.md")
            save_report(report_text, report_path)
            print(f"Report saved to: {report_path}\n")

        return suite_results


if __name__ == "__main__":
    # Windows console defaults to cp1252; reconfigure to UTF-8 so emoji output works.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="DojoTesuto CLI Runner")
    parser.add_argument("suite", nargs="?", default="core", help="Suite name to run (default: core)")
    parser.add_argument("--noninteractive", action="store_true", help="Run in non-interactive mode")
    parser.add_argument("--forge", action="store_true", help="Enable Forge mode (reflection + patching)")
    parser.add_argument("--save-report", action="store_true", help="Save session report to reports/")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner = DojoTesutoRunner(base_dir, noninteractive=args.noninteractive, forge=args.forge)
    runner.run_suite(args.suite, save_report_file=args.save_report)