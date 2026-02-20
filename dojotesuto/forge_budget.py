"""
ForgeBudget — suite-level resource limits for Forge mode.

Quest-level budgets (max_steps, max_seconds, max_tokens) already constrain
individual challenge execution. This module adds limits on the reflection
layer itself, which quest budgets cannot see:

  - max_reflection_seconds : timeout per reflection handler call
  - max_reflections        : max number of reflection calls per suite run
  - max_suite_seconds      : hard wall-clock limit for the entire suite

These are intentionally separate from quest budgets so the two concerns
stay clean: quest budgets govern agent behavior, Forge budgets govern
infrastructure cost.
"""

import threading


# Defaults — conservative but not restrictive for normal use
DEFAULT_REFLECTION_TIMEOUT  = 60    # seconds per reflection call
DEFAULT_MAX_REFLECTIONS     = 10    # per suite run
DEFAULT_MAX_SUITE_SECONDS   = 1800  # 30 minutes total


class ForgeBudgetExceeded(Exception):
    """Raised when a Forge-level budget limit is hit."""
    pass


class ReflectionTimeout(ForgeBudgetExceeded):
    """Raised when a single reflection call exceeds its time limit."""
    pass


class ForgeBudget:
    """
    Tracks and enforces Forge-level resource limits across a suite run.

    Usage:
        budget = ForgeBudget(max_reflection_seconds=30, max_reflections=5)
        budget.start_suite()

        # Before each reflection call:
        budget.check_suite_time()
        budget.check_reflection_count()

        # Wrap the actual handler call:
        result = budget.call_with_timeout(handler, request)

        budget.record_reflection()
    """

    def __init__(
        self,
        max_reflection_seconds=DEFAULT_REFLECTION_TIMEOUT,
        max_reflections=DEFAULT_MAX_REFLECTIONS,
        max_suite_seconds=DEFAULT_MAX_SUITE_SECONDS,
    ):
        self.max_reflection_seconds = max_reflection_seconds
        self.max_reflections        = max_reflections
        self.max_suite_seconds      = max_suite_seconds

        self._suite_start     = None
        self._reflection_count = 0

    def start_suite(self):
        import time
        self._suite_start      = time.monotonic()
        self._reflection_count = 0

    def elapsed_suite(self):
        import time
        if self._suite_start is None:
            return 0.0
        return time.monotonic() - self._suite_start

    def check_suite_time(self):
        """Raise ForgeBudgetExceeded if the suite wall-clock limit is hit."""
        elapsed = self.elapsed_suite()
        if elapsed > self.max_suite_seconds:
            raise ForgeBudgetExceeded(
                f"Suite time limit reached: {elapsed:.0f}s elapsed "
                f"(max {self.max_suite_seconds}s). Halting Forge mode."
            )

    def check_reflection_count(self):
        """Raise ForgeBudgetExceeded if the reflection call limit is hit."""
        if self._reflection_count >= self.max_reflections:
            raise ForgeBudgetExceeded(
                f"Reflection call limit reached: {self._reflection_count} "
                f"reflections used (max {self.max_reflections}). "
                f"Remaining quests will not trigger Forge reflection."
            )

    def record_reflection(self):
        """Increment the reflection counter after a successful call."""
        self._reflection_count += 1

    def call_with_timeout(self, handler, request):
        """
        Call handler(request) with a per-call timeout.

        Uses a daemon thread so the main process is never blocked indefinitely.
        Raises ReflectionTimeout if the handler doesn't respond in time.
        Returns the handler's return value on success.
        """
        result    = [None]
        exc       = [None]
        completed = threading.Event()

        def _run():
            try:
                result[0] = handler(request)
            except Exception as e:
                exc[0] = e
            finally:
                completed.set()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        finished = completed.wait(timeout=self.max_reflection_seconds)

        if not finished:
            raise ReflectionTimeout(
                f"Reflection handler timed out after {self.max_reflection_seconds}s. "
                f"Quest marked as failed."
            )

        if exc[0] is not None:
            raise exc[0]

        return result[0]

    def summary(self):
        """Return a short summary string for the report."""
        return (
            f"Forge budget: {self._reflection_count}/{self.max_reflections} reflections used, "
            f"{self.elapsed_suite():.0f}s elapsed"
        )
