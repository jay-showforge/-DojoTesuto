import json
from datetime import datetime

def _bar(score, width=20):
    """Render a simple ASCII progress bar."""
    filled = int(round(score / 100 * width))
    return f"[{'█' * filled}{'░' * (width - filled)}] {score:.0f}%"

def _grade(score):
    if score == 100: return "S"
    if score >= 80:  return "A"
    if score >= 60:  return "B"
    if score >= 40:  return "C"
    if score >= 20:  return "D"
    return "F"

def generate_report(suite_name, quest_names, suite_results, forge=False, print_output=True):
    """
    Generate a DojoTesuto session report from suite results.

    Returns the report as a string. Optionally prints it.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(suite_results)

    passed        = sum(1 for r in suite_results if r["initial"]["status"] == "PASS")
    failed        = sum(1 for r in suite_results if r["initial"]["status"] == "FAIL")
    skipped       = sum(1 for r in suite_results if r["initial"]["status"] == "SKIP")
    variants_won  = sum(1 for r in suite_results if r["variant_pass"])
    patches_made  = sum(r["skills_guardrails_created"] for r in suite_results)

    primary_rate  = (passed / (total - skipped) * 100) if (total - skipped) > 0 else 0
    variant_rate  = (variants_won / failed * 100) if failed > 0 else 100 if passed == total else 0
    recovery_rate = variant_rate

    # Overall resilience score:
    # Full credit for primary pass, partial credit for variant recovery after failure
    resilience_score = (
        (passed * 100 + variants_won * 60) / (total * 100) * 100
    ) if total > 0 else 0

    lines = []
    w = 52  # report width

    def rule(char="─"):
        lines.append(char * w)

    def center(text):
        lines.append(text.center(w))

    def row(label, value, indent=0):
        pad = " " * indent
        lines.append(f"{pad}{label:<28}{value}")

    rule("═")
    center("🥋  DojoTesuto Session Report")
    center(f"Suite: {suite_name}   |   {now}")
    rule("═")

    lines.append("")
    lines.append("  QUEST BREAKDOWN")
    rule()

    for i, (name, result) in enumerate(zip(quest_names, suite_results)):
        initial = result["initial"]
        status = initial["status"]
        score = initial["score"]

        if status == "SKIP":
            status_str = "⏭️  SKIP"
            detail = ""
        elif status == "PASS":
            status_str = "✅ PASS"
            detail = f"  score: {score:.0f}%"
        else:
            status_str = "❌ FAIL"
            detail = f"  score: {score:.0f}%"
            if forge and result["variant_pass"]:
                detail += "  →  ✅ recovered on variant"
            elif forge and result["post_learning"] is not None:
                detail += "  →  ❌ variant also failed"

        lines.append(f"  {name:<26} {status_str}{detail}")

    lines.append("")
    rule()
    lines.append("  SCORES")
    rule()

    row("Primary pass rate:",  _bar(primary_rate),   indent=2)

    if forge:
        row("Variant recovery rate:", _bar(recovery_rate), indent=2)
        row("Resilience score:",      _bar(resilience_score), indent=2)
        lines.append("")
        row("Guardrail patches applied:", str(patches_made), indent=2)

    lines.append("")
    rule()
    lines.append("  SUMMARY")
    rule()

    row("Total quests:",  str(total),   indent=2)
    row("Passed:",        f"✅ {passed}",  indent=2)
    row("Failed:",        f"❌ {failed}",  indent=2)
    if skipped:
        row("Skipped:", f"⏭️  {skipped}", indent=2)
    if forge:
        row("Variants won:", f"🔁 {variants_won} / {failed}", indent=2)

    lines.append("")

    # Verdict
    grade = _grade(resilience_score if forge else primary_rate)
    if grade == "S":
        verdict = "Your agent is dojo-hardened. Ship it. 🥋"
    elif grade == "A":
        verdict = "Strong resilience. Minor gaps remain."
    elif grade == "B":
        verdict = "Solid foundation. Keep training."
    elif grade == "C":
        verdict = "Meaningful weaknesses. Forge mode recommended."
    else:
        verdict = "Significant work needed. Run Forge mode."

    rule("═")
    center(f"Grade: {grade}   |   {verdict}")
    rule("═")

    report = "\n".join(lines)

    if print_output:
        print("\n" + report + "\n")

    return report


def save_report(report_text, output_path):
    """Save the report to a markdown file."""
    with open(output_path, "w") as f:
        f.write("```\n")
        f.write(report_text)
        f.write("\n```\n")
