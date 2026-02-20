"""
Tests for ForgeBudget — suite-level Forge resource limits.
Each test uses a real repro, no mocks of the thing being tested.
"""
import time
import pytest
import tempfile
import os
from dojotesuto.forge_budget import (
    ForgeBudget, ForgeBudgetExceeded, ReflectionTimeout
)
from dojotesuto.runner import DojoTesutoRunner


# ── ForgeBudget unit tests ────────────────────────────────────────────────────

class TestReflectionTimeout:
    def test_fast_handler_passes(self):
        budget = ForgeBudget(max_reflection_seconds=2)
        result = budget.call_with_timeout(lambda r: {"ok": True}, {})
        assert result == {"ok": True}

    def test_slow_handler_raises_timeout(self):
        budget = ForgeBudget(max_reflection_seconds=0.1)
        def slow_handler(request):
            time.sleep(5)
            return {"ok": True}
        with pytest.raises(ReflectionTimeout):
            budget.call_with_timeout(slow_handler, {})

    def test_timeout_is_reflection_timeout_subclass(self):
        """ReflectionTimeout is a ForgeBudgetExceeded so callers can catch either."""
        assert issubclass(ReflectionTimeout, ForgeBudgetExceeded)

    def test_handler_exception_propagates(self):
        budget = ForgeBudget(max_reflection_seconds=2)
        def bad_handler(req):
            raise ValueError("handler broke")
        with pytest.raises(ValueError, match="handler broke"):
            budget.call_with_timeout(bad_handler, {})


class TestReflectionCountLimit:
    def test_under_limit_passes(self):
        budget = ForgeBudget(max_reflections=3)
        budget.start_suite()
        budget.record_reflection()
        budget.record_reflection()
        budget.check_reflection_count()  # should not raise

    def test_at_limit_raises(self):
        budget = ForgeBudget(max_reflections=2)
        budget.start_suite()
        budget.record_reflection()
        budget.record_reflection()
        with pytest.raises(ForgeBudgetExceeded, match="limit reached"):
            budget.check_reflection_count()

    def test_zero_limit_blocks_immediately(self):
        budget = ForgeBudget(max_reflections=0)
        budget.start_suite()
        with pytest.raises(ForgeBudgetExceeded):
            budget.check_reflection_count()


class TestSuiteTimeLimit:
    def test_within_time_passes(self):
        budget = ForgeBudget(max_suite_seconds=60)
        budget.start_suite()
        budget.check_suite_time()  # should not raise

    def test_elapsed_time_raises(self):
        budget = ForgeBudget(max_suite_seconds=0.05)
        budget.start_suite()
        time.sleep(0.1)
        with pytest.raises(ForgeBudgetExceeded, match="time limit"):
            budget.check_suite_time()

    def test_elapsed_without_start_is_safe(self):
        budget = ForgeBudget(max_suite_seconds=60)
        # Should not raise even if start_suite() was never called
        budget.check_suite_time()


class TestSummary:
    def test_summary_format(self):
        budget = ForgeBudget(max_reflections=5)
        budget.start_suite()
        budget.record_reflection()
        budget.record_reflection()
        s = budget.summary()
        assert "2/5" in s
        assert "reflections" in s


# ── Integration: budget wired into runner ─────────────────────────────────────

class TestRunnerForgeBudgetIntegration:

    def _runner(self, tmp_path, budget):
        os.makedirs(os.path.join(tmp_path, "challenges"), exist_ok=True)
        r = DojoTesutoRunner(str(tmp_path), forge=True, forge_budget=budget)
        return r

    def test_timeout_handler_does_not_crash_runner(self, tmp_path):
        """A hanging reflection handler should not block the runner forever."""
        budget = ForgeBudget(max_reflection_seconds=0.1, max_reflections=5)
        runner = self._runner(str(tmp_path), budget)

        def hanging_handler(req):
            time.sleep(10)
            return {}

        runner.register_reflection_handler(hanging_handler)

        # Simulate the forge reflection call as runner would
        runner.forge_budget.start_suite()
        request = runner.reflection_engine.build_request(
            {"id": "test", "description": "x"}, [], "", "", ""
        )
        start = time.monotonic()
        try:
            runner.forge_budget.call_with_timeout(runner.reflection_engine._handler, request)
            timed_out = False
        except ReflectionTimeout:
            timed_out = True
        elapsed = time.monotonic() - start

        assert timed_out, "Should have timed out"
        assert elapsed < 2.0, f"Took {elapsed:.2f}s — handler blocked too long"

    def test_reflection_count_limit_respected(self, tmp_path):
        """After max_reflections calls, further reflections are blocked."""
        budget = ForgeBudget(max_reflections=2, max_reflection_seconds=5)
        runner = self._runner(str(tmp_path), budget)
        runner.forge_budget.start_suite()

        runner.forge_budget.record_reflection()
        runner.forge_budget.record_reflection()

        with pytest.raises(ForgeBudgetExceeded):
            runner.forge_budget.check_reflection_count()

    def test_default_budget_is_created_automatically(self, tmp_path):
        """Runner creates a default ForgeBudget if none is supplied."""
        os.makedirs(os.path.join(str(tmp_path), "challenges"), exist_ok=True)
        runner = DojoTesutoRunner(str(tmp_path), forge=True)
        assert runner.forge_budget is not None
        assert runner.forge_budget.max_reflection_seconds == 60
        assert runner.forge_budget.max_reflections == 10
        assert runner.forge_budget.max_suite_seconds == 1800

    def test_custom_budget_values_respected(self, tmp_path):
        budget = ForgeBudget(max_reflection_seconds=5, max_reflections=3, max_suite_seconds=120)
        runner = self._runner(str(tmp_path), budget)
        assert runner.forge_budget.max_reflection_seconds == 5
        assert runner.forge_budget.max_reflections == 3
        assert runner.forge_budget.max_suite_seconds == 120
