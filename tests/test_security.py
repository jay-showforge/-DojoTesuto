"""
DojoTesuto Security Test Suite
Red-team verified tests for confirmed issues only.

Findings addressed:
  ISSUE-1 (HIGH)  — Null byte in skill_patch path/content crashed with unhandled ValueError
  ISSUE-2 (MED)   — Oversized reflection payloads written to SOUL.md without limit
  ISSUE-3 (INFO)  — YAML !!python/object tags rejected by safe_load (already correct, tested here)
  ISSUE-4 (INFO)  — Sandbox path traversal blocked correctly (tested here)
"""

import os
import sys
import tempfile
import unittest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dojotesuto.runner import DojoTesutoRunner, _validate_reflection_response
from dojotesuto.validator import validate_quest


# ── Helpers ────────────────────────────────────────────────────────────────

def make_runner(base):
    os.makedirs(os.path.join(base, "challenges"), exist_ok=True)
    return DojoTesutoRunner(base, forge=True)

def reflection_with_path(path, content="PWNED"):
    return {
        "failure_reason": "test",
        "guardrail_patch": "",
        "skill_patch": {"create_files": [{"path": path, "content": content}]},
        "confidence": 0.5
    }


# ── ISSUE-1: Null byte handling ────────────────────────────────────────────

class TestNullByteBlocked(unittest.TestCase):

    def test_null_byte_in_path_rejected_by_validator(self):
        data = reflection_with_path("skills_generated/\x00evil.txt")
        valid, msg = _validate_reflection_response(data)
        self.assertFalse(valid)
        self.assertIn("null byte", msg)

    def test_null_byte_in_content_rejected_by_validator(self):
        data = reflection_with_path("skills_generated/ok.txt", content="A\x00B")
        valid, msg = _validate_reflection_response(data)
        self.assertFalse(valid)
        self.assertIn("null byte", msg)

    def test_null_byte_in_modify_append_rejected(self):
        data = {
            "failure_reason": "x", "guardrail_patch": "",
            "skill_patch": {"modify_files": [{"path": "SOUL.md", "append": "A\x00B"}]},
            "confidence": 0.5
        }
        valid, msg = _validate_reflection_response(data)
        self.assertFalse(valid)
        self.assertIn("null byte", msg)

    def test_null_byte_does_not_crash_apply_patch(self):
        """End-to-end: null byte rejected before apply_patch is called, no ValueError."""
        with tempfile.TemporaryDirectory() as base:
            runner = make_runner(base)
            data = reflection_with_path("skills_generated/\x00evil.txt")
            valid, _ = _validate_reflection_response(data)
            if not valid:
                return  # correctly blocked — no crash
            # If validator somehow passes, apply_patch must also not crash
            try:
                runner.apply_patch("test", data, "resp", [])
            except ValueError:
                self.fail("Null byte caused unhandled ValueError crash in apply_patch")


# ── ISSUE-2: Oversized payload limits ──────────────────────────────────────

class TestPayloadSizeLimits(unittest.TestCase):
    _MAX = 512_000

    def test_oversized_guardrail_patch_rejected(self):
        data = {
            "failure_reason": "x",
            "guardrail_patch": "A" * (self._MAX + 1),
            "skill_patch": {},
            "confidence": 0.9
        }
        valid, msg = _validate_reflection_response(data)
        self.assertFalse(valid)
        self.assertIn("exceeds max size", msg)

    def test_oversized_skill_content_rejected(self):
        data = reflection_with_path("skills_generated/big.md", content="B" * (self._MAX + 1))
        valid, msg = _validate_reflection_response(data)
        self.assertFalse(valid)
        self.assertIn("exceeds max size", msg)

    def test_oversized_modify_append_rejected(self):
        data = {
            "failure_reason": "x", "guardrail_patch": "",
            "skill_patch": {"modify_files": [{"path": "SOUL.md", "append": "C" * (self._MAX + 1)}]},
            "confidence": 0.9
        }
        valid, msg = _validate_reflection_response(data)
        self.assertFalse(valid)
        self.assertIn("exceeds max size", msg)

    def test_at_limit_payload_allowed(self):
        data = {
            "failure_reason": "x",
            "guardrail_patch": "A" * self._MAX,
            "skill_patch": {},
            "confidence": 0.9
        }
        valid, msg = _validate_reflection_response(data)
        self.assertTrue(valid, f"At-limit payload was rejected: {msg}")


# ── ISSUE-3: YAML code execution (safe_load verification) ─────────────────

class TestYAMLSafety(unittest.TestCase):

    def _write_quest(self, d, filename, content):
        path = os.path.join(d, filename)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_python_object_tag_does_not_execute(self):
        evil = """
id: evil
tier: squire
category: safety
description: test
mock: true
budget: {max_steps: 5, max_seconds: 10, max_tokens: 1000}
primary:
  steps:
    - type: ask
      payload:
        question: !!python/object/apply:os.system ["echo PWNED > /tmp/yaml_pwned_test.txt"]
  assertions:
    - type: budget_ok
      payload: {}
variants:
  - steps:
      - type: ask
        payload: {question: safe}
    assertions:
      - type: budget_ok
        payload: {}
"""
        with tempfile.TemporaryDirectory() as d:
            path = self._write_quest(d, "evil.yaml", evil)
            try:
                validate_quest(path)
            except Exception:
                pass  # rejected is fine
            self.assertFalse(
                os.path.exists("/tmp/yaml_pwned_test.txt"),
                "!!python/object tag executed OS command — CRITICAL"
            )

    def test_shell_string_in_text_field_is_plain_text(self):
        quest = """
id: shell-test
tier: squire
category: safety
description: test
mock: true
budget: {max_steps: 5, max_seconds: 10, max_tokens: 1000}
primary:
  steps:
    - type: inject_text
      payload:
        source: test
        text: "$(rm -rf /tmp/dojo_shell_test); `whoami`"
  assertions:
    - type: budget_ok
      payload: {}
variants:
  - steps:
      - type: ask
        payload: {question: safe}
    assertions:
      - type: budget_ok
        payload: {}
"""
        with tempfile.TemporaryDirectory() as d:
            path = self._write_quest(d, "shell.yaml", quest)
            is_valid, msg = validate_quest(path)
            self.assertTrue(is_valid, f"Quest rejected unexpectedly: {msg}")


# ── ISSUE-4: Sandbox path traversal ────────────────────────────────────────

class TestSandboxEnforcement(unittest.TestCase):

    def _run_attack(self, base, attack_path):
        runner = make_runner(base)
        data = reflection_with_path(attack_path)
        is_valid, _ = _validate_reflection_response(data)
        if is_valid:
            runner.apply_patch("test", data, "resp", [])

    def test_dot_dot_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as base:
            self._run_attack(base, "../../../tmp/traversal_test.txt")
            self.assertFalse(os.path.exists("/tmp/traversal_test.txt"))

    def test_absolute_path_blocked(self):
        with tempfile.TemporaryDirectory() as base:
            self._run_attack(base, "/tmp/absolute_test.txt")
            self.assertFalse(os.path.exists("/tmp/absolute_test.txt"))

    def test_runner_py_not_writable(self):
        with tempfile.TemporaryDirectory() as base:
            self._run_attack(base, "dojotesuto/runner.py")
            target = os.path.join(base, "dojotesuto/runner.py")
            self.assertFalse(
                os.path.exists(target) and open(target).read() == "PWNED",
                "runner.py was overwritten via skill_patch"
            )

    def test_ci_workflow_not_writable(self):
        with tempfile.TemporaryDirectory() as base:
            self._run_attack(base, ".github/workflows/ci.yml")
            target = os.path.join(base, ".github/workflows/ci.yml")
            self.assertFalse(
                os.path.exists(target) and open(target).read() == "PWNED"
            )

    def test_skills_generated_is_writable(self):
        """Confirm legitimate paths still work."""
        with tempfile.TemporaryDirectory() as base:
            runner = make_runner(base)
            data = reflection_with_path("skills_generated/legit_skill.md", content="# My skill")
            is_valid, msg = _validate_reflection_response(data)
            self.assertTrue(is_valid, f"Legitimate path rejected: {msg}")
            runner.apply_patch("test", data, "resp", [])
            target = os.path.join(base, "skills_generated/legit_skill.md")
            self.assertTrue(os.path.exists(target))
            self.assertEqual(open(target).read(), "# My skill")

    def test_prefix_collision_blocked(self):
        """'skills_generatedEvil' must not match 'skills_generated' sandbox."""
        with tempfile.TemporaryDirectory() as base:
            self._run_attack(base, "skills_generatedEvil/escape.txt")
            target = os.path.join(base, "skills_generatedEvil/escape.txt")
            self.assertFalse(os.path.exists(target))


# ── Variant enforcement ────────────────────────────────────────────────────

class TestVariantEnforcement(unittest.TestCase):

    def test_variant_pass_false_without_forge(self):
        """variant_pass must never be True if forge=False."""
        with tempfile.TemporaryDirectory() as base:
            os.makedirs(os.path.join(base, "challenges/core"), exist_ok=True)
            quest = {
                "id": "vtest", "tier": "squire", "category": "safety",
                "description": "test", "mock": True,
                "budget": {"max_steps": 5, "max_seconds": 10, "max_tokens": 1000},
                "primary": {
                    "steps": [{"type": "set_fact", "payload": {"key": "x", "value": "1"}}],
                    "assertions": [{"type": "must_equal", "payload": {"key": "x", "value": "999"}}]
                },
                "variants": [{
                    "steps": [{"type": "set_fact", "payload": {"key": "y", "value": "2"}}],
                    "assertions": [{"type": "must_equal", "payload": {"key": "y", "value": "2"}}]
                }]
            }
            qpath = os.path.join(base, "challenges/core/vtest.yaml")
            with open(qpath, "w") as f:
                yaml.dump(quest, f)

            runner = DojoTesutoRunner(base, noninteractive=True, forge=False)
            result = runner.run_quest(qpath)
            self.assertFalse(result["variant_pass"])
            self.assertIsNone(result["post_learning"])

    def test_variant_pass_false_without_handler(self):
        """variant_pass must be False when forge=True but no handler registered."""
        with tempfile.TemporaryDirectory() as base:
            os.makedirs(os.path.join(base, "challenges/core"), exist_ok=True)
            quest = {
                "id": "vtest2", "tier": "squire", "category": "safety",
                "description": "test", "mock": True,
                "budget": {"max_steps": 5, "max_seconds": 10, "max_tokens": 1000},
                "primary": {
                    "steps": [{"type": "set_fact", "payload": {"key": "x", "value": "1"}}],
                    "assertions": [{"type": "must_equal", "payload": {"key": "x", "value": "999"}}]
                },
                "variants": [{
                    "steps": [{"type": "set_fact", "payload": {"key": "y", "value": "2"}}],
                    "assertions": [{"type": "must_equal", "payload": {"key": "y", "value": "2"}}]
                }]
            }
            qpath = os.path.join(base, "challenges/core/vtest2.yaml")
            with open(qpath, "w") as f:
                yaml.dump(quest, f)

            runner = DojoTesutoRunner(base, noninteractive=True, forge=True)
            # No handler registered
            result = runner.run_quest(qpath)
            self.assertFalse(result["variant_pass"])
            self.assertIsNone(result["post_learning"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
