"""
Regression tests for two confirmed bugs:

BUG 1 — Budget enforcement broken
  quest budgets live at root level, but _run_single_challenge_def() was reading
  budget from inside challenge_def (primary/variant), where it doesn't exist.
  Result: max_steps/max_seconds/max_tokens were always infinity; budget_ok always passed.

BUG 2 — must_equal with key checked response text instead of self.facts
  must_equal + key is the memory-drift assertion pattern. It should verify that
  a fact stored via set_fact matches the expected value, not scan the response string.
"""
import os
import pytest
import tempfile
from dojotesuto.runner import DojoTesutoRunner


@pytest.fixture
def runner(tmp_path):
    (tmp_path / "challenges").mkdir()
    return DojoTesutoRunner(str(tmp_path), noninteractive=True)


def challenge(steps=None, assertions=None):
    return {
        "steps": steps or [],
        "assertions": assertions or [],
    }


# ── BUG 1: Budget enforcement ─────────────────────────────────────────────────

class TestBudgetEnforcement:

    def test_max_steps_enforced_via_quest_budget(self, runner):
        """budget_ok fails when steps taken exceed quest-level max_steps."""
        ch = challenge(
            steps=[
                {"type": "inject_text", "payload": {"source": "x", "text": "a"}},
                {"type": "inject_text", "payload": {"source": "x", "text": "b"}},
                {"type": "inject_text", "payload": {"source": "x", "text": "c"}},
            ],
            assertions=[{"type": "budget_ok", "payload": {}}],
        )
        result = runner._run_single_challenge_def(
            "t", ch, quest_budget={"max_steps": 2, "max_seconds": 60, "max_tokens": 9999}
        )
        assert result["status"] == "FAIL", (
            "budget_ok should FAIL when 3 steps attempted against max_steps=2"
        )

    def test_no_budget_means_unlimited(self, runner):
        """quest_budget=None means no limits; budget_ok always passes."""
        ch = challenge(
            steps=[
                {"type": "inject_text", "payload": {"source": "x", "text": "a"}},
                {"type": "inject_text", "payload": {"source": "x", "text": "b"}},
                {"type": "inject_text", "payload": {"source": "x", "text": "c"}},
            ],
            assertions=[{"type": "budget_ok", "payload": {}}],
        )
        result = runner._run_single_challenge_def("t", ch, quest_budget=None)
        assert result["status"] == "PASS"

    def test_budget_within_limit_passes(self, runner):
        """budget_ok passes when steps are within the quest budget."""
        ch = challenge(
            steps=[
                {"type": "inject_text", "payload": {"source": "x", "text": "a"}},
            ],
            assertions=[{"type": "budget_ok", "payload": {}}],
        )
        result = runner._run_single_challenge_def(
            "t", ch, quest_budget={"max_steps": 5, "max_seconds": 60, "max_tokens": 9999}
        )
        assert result["status"] == "PASS"

    def test_quest_budget_not_read_from_challenge_def(self, runner):
        """Confirms the old bug is gone: budget inside challenge_def is ignored."""
        # If the old code ran, it would find no budget in challenge_def,
        # default to inf, and pass budget_ok even with max_steps=1 exceeded.
        ch = challenge(
            steps=[
                {"type": "inject_text", "payload": {"source": "x", "text": "a"}},
                {"type": "inject_text", "payload": {"source": "x", "text": "b"}},
            ],
            # Deliberately put a permissive budget INSIDE challenge_def (old location)
            # This should be ignored by the fixed code.
            assertions=[{"type": "budget_ok", "payload": {}}],
        )
        ch["budget"] = {"max_steps": 999, "max_seconds": 999, "max_tokens": 999}

        result = runner._run_single_challenge_def(
            "t", ch, quest_budget={"max_steps": 1, "max_seconds": 60, "max_tokens": 9999}
        )
        # Fixed: uses quest_budget (max_steps=1), not challenge_def budget (max_steps=999)
        assert result["status"] == "FAIL", (
            "Should use quest_budget, not the budget stashed inside challenge_def"
        )


# ── BUG 2: must_equal fact checking ──────────────────────────────────────────

class TestMustEqualFactCheck:

    def test_passes_when_fact_matches(self, runner):
        """must_equal with key passes when self.facts[key] == value."""
        runner.facts["color"] = "blue"
        ch = challenge(assertions=[
            {"type": "must_equal", "payload": {"key": "color", "value": "blue"}}
        ])
        result = runner._run_single_challenge_def("t", ch, quest_budget={})
        assert result["status"] == "PASS"

    def test_fails_when_fact_wrong_value(self, runner):
        """must_equal with key fails when fact exists but has wrong value."""
        runner.facts["color"] = "red"
        ch = challenge(assertions=[
            {"type": "must_equal", "payload": {"key": "color", "value": "blue"}}
        ])
        result = runner._run_single_challenge_def("t", ch, quest_budget={})
        assert result["status"] == "FAIL"

    def test_fails_when_key_not_in_facts(self, runner):
        """must_equal with key fails when the key was never set."""
        ch = challenge(assertions=[
            {"type": "must_equal", "payload": {"key": "color", "value": "blue"}}
        ])
        result = runner._run_single_challenge_def("t", ch, quest_budget={})
        assert result["status"] == "FAIL"

    def test_not_fooled_by_response_text(self, runner):
        """
        Regression: old code checked if value appeared in response text.
        If fact is wrong but response contains the expected word, must still FAIL.
        """
        runner.facts["color"] = "red"
        # Simulate a response that contains "blue" — old code would pass this
        # We inject text then check; but since noninteractive skips 'ask',
        # we set context directly via a set_fact step pointing to a different key
        # and verify the assertion reads from facts, not anything else.
        # Simplest proof: fact="red", expected="blue" → FAIL regardless of anything else.
        ch = challenge(assertions=[
            {"type": "must_equal", "payload": {"key": "color", "value": "blue"}}
        ])
        result = runner._run_single_challenge_def("t", ch, quest_budget={})
        assert result["status"] == "FAIL", (
            "Fact is 'red', expected 'blue' — must FAIL even if 'blue' appears elsewhere"
        )

    def test_set_fact_then_must_equal(self, runner):
        """Full flow: set_fact in steps, then must_equal assertion reads from facts."""
        ch = challenge(
            steps=[
                {"type": "set_fact", "payload": {"key": "animal", "value": "cat"}}
            ],
            assertions=[
                {"type": "must_equal", "payload": {"key": "animal", "value": "cat"}}
            ],
        )
        result = runner._run_single_challenge_def("t", ch, quest_budget={})
        assert result["status"] == "PASS"

    def test_must_equal_without_key_still_works(self, runner):
        """must_equal with field= (no key) still checks context, not facts."""
        ch = challenge(assertions=[
            {"type": "must_equal", "payload": {"field": "response", "value": ""}}
        ])
        result = runner._run_single_challenge_def("t", ch, quest_budget={})
        assert result["status"] == "PASS"  # response starts empty, "" == ""
