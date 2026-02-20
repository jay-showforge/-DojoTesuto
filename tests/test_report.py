import pytest
from dojotesuto.report import generate_report

def _make_result(status, score=100, variant_pass=False, post_learning=None):
    return {
        "id": "test-quest",
        "initial": {"status": status, "score": score, "failed_assertions": [], "agent_response": ""},
        "post_learning": post_learning,
        "variant_pass": variant_pass,
        "skills_guardrails_created": 1 if variant_pass else 0
    }

def test_report_all_pass():
    results = [_make_result("PASS", 100) for _ in range(3)]
    report = generate_report("core", ["q1", "q2", "q3"], results, forge=False, print_output=False)
    assert "Grade: S" in report
    assert "100%" in report

def test_report_all_fail():
    results = [_make_result("FAIL", 0) for _ in range(3)]
    report = generate_report("core", ["q1", "q2", "q3"], results, forge=False, print_output=False)
    assert "Grade:" in report
    assert "❌" in report

def test_report_forge_recovery():
    results = [
        _make_result("FAIL", 33, variant_pass=True,
                     post_learning={"status": "PASS", "score": 100, "failed_assertions": [], "agent_response": ""}),
        _make_result("PASS", 100),
    ]
    report = generate_report("core", ["q1", "q2"], results, forge=True, print_output=False)
    assert "recovered on variant" in report
    assert "Variant recovery rate" in report

def test_report_skip():
    results = [_make_result("SKIP", 0)]
    report = generate_report("core", ["q1"], results, forge=False, print_output=False)
    assert "SKIP" in report

def test_report_returns_string():
    results = [_make_result("PASS", 100)]
    report = generate_report("core", ["q1"], results, forge=False, print_output=False)
    assert isinstance(report, str)
    assert len(report) > 0
