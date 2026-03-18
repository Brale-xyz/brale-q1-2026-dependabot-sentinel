#!/usr/bin/env python3
"""
Dependabot Sentinel — Local Demo Runner
========================================
Runs all demo scenarios through the actual pipeline scripts without needing
a real GitHub repo or live dependabot PRs.

Usage:
    python3 demo/run_demo.py                        # run all scenarios
    python3 demo/run_demo.py --scenario 1           # run scenario 1 only
    python3 demo/run_demo.py --scenario 4           # run the adversarial test
    python3 demo/run_demo.py --no-llm               # classify only, skip Claude
    python3 demo/run_demo.py --list                 # list available scenarios

Requirements:
    pip install anthropic pyyaml packaging
    export ANTHROPIC_API_KEY=sk-ant-...
"""

import argparse
import json
import os
import re
import sys
import time
import textwrap
from pathlib import Path

# ── Terminal colors ──────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def c(color, text): return f"{color}{text}{RESET}"
def header(text):   print(f"\n{BOLD}{CYAN}{'─'*60}\n  {text}\n{'─'*60}{RESET}")
def ok(text):       print(f"  {GREEN}✅ {text}{RESET}")
def fail(text):     print(f"  {RED}❌ {text}{RESET}")
def warn(text):     print(f"  {YELLOW}⚠️  {text}{RESET}")
def info(text):     print(f"  {DIM}{text}{RESET}")

# ── Repo root detection ───────────────────────────────────────────────────────
DEMO_DIR    = Path(__file__).parent
REPO_ROOT   = DEMO_DIR.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CRITERIA_DIR = REPO_ROOT / ".github" / "review-criteria"
SCENARIOS_DIR = DEMO_DIR / "scenarios"

sys.path.insert(0, str(SCRIPTS_DIR))


# ── Load scenario files ───────────────────────────────────────────────────────
def load_scenarios() -> list[dict]:
    files = sorted(SCENARIOS_DIR.glob("scenario_*.json"))
    scenarios = []
    for f in files:
        with open(f) as fp:
            s = json.load(fp)
            s["_file"] = f.name
            s["_number"] = int(re.search(r"scenario_(\d+)", f.name).group(1))
            scenarios.append(s)
    return scenarios


# ── Classification (reuses actual classify logic) ────────────────────────────
def run_classify(scenario: dict) -> dict:
    """Run the deterministic classification step against a scenario."""
    import yaml

    result = {
        "eligible": True,
        "reasons_ineligible": [],
        "bump_type": scenario.get("bump_type", "unknown"),
        "package_name": scenario.get("package_name"),
        "old_version": scenario.get("old_version"),
        "new_version": scenario.get("new_version"),
        "ecosystem": scenario.get("ecosystem", "unknown"),
    }

    # Load critical deps
    crit_path = CRITERIA_DIR / "critical-dependencies.yml"
    critical_deps = {}
    if crit_path.exists():
        with open(crit_path) as f:
            critical_deps = yaml.safe_load(f) or {}

    # Check major bump
    if result["bump_type"] == "major":
        result["eligible"] = False
        result["reasons_ineligible"].append("major version bump")

    # Check critical dep
    ecosystem = result["ecosystem"]
    package = result["package_name"] or ""
    deps_for_ecosystem = critical_deps.get(ecosystem, [])
    if any(
        package == dep or package.startswith(dep + "/") or package.endswith("/" + dep)
        for dep in deps_for_ecosystem
    ):
        result["eligible"] = False
        result["reasons_ineligible"].append(f"'{package}' is in critical-dependencies list")

    # Check files
    ALLOWED_PATTERNS = [
        r"requirements.*\.txt$", r"Pipfile(\.lock)?$", r"pyproject\.toml$",
        r"poetry\.lock$", r"package\.json$", r"package-lock\.json$",
        r"yarn\.lock$", r"pnpm-lock\.yaml$", r"go\.(mod|sum)$",
        r"Cargo\.(toml|lock)$", r"Gemfile(\.lock)?$", r"pom\.xml$",
        r"build\.gradle(\.kts)?$", r"setup\.cfg$",
    ]
    bad_files = [
        f["filename"] for f in scenario.get("changed_files", [])
        if not any(re.search(p, f["filename"]) for p in ALLOWED_PATTERNS)
    ]
    if bad_files:
        result["eligible"] = False
        result["reasons_ineligible"].append(f"unexpected files: {bad_files}")

    if result["bump_type"] in ("patch", "minor"):
        result["criteria_file"] = f"dependabot-{result['bump_type']}.md"
    else:
        result["criteria_file"] = "_base.md"

    return result


# ── LLM Review ───────────────────────────────────────────────────────────────
def run_llm_review(scenario: dict, classification: dict) -> dict:
    """Call the actual run_claude_review logic with mock data."""
    import tempfile, json, subprocess

    # Write diff to temp file
    diff_data = scenario.get("diff", [])
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(diff_data, f)
        diff_file = f.name

    # Write release notes to temp file
    notes = scenario.get("release_notes", "(no release notes provided)")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(notes)
        notes_file = f.name

    criteria_file = CRITERIA_DIR / classification.get("criteria_file", "_base.md")
    base_criteria  = CRITERIA_DIR / "_base.md"
    policy_file    = CRITERIA_DIR / "_auto-approve-policy.md"

    classification_str = json.dumps(classification)

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "run_claude_review.py"),
         "--criteria-file",   str(criteria_file),
         "--base-criteria",   str(base_criteria),
         "--policy-file",     str(policy_file),
         "--diff-file",       diff_file,
         "--release-notes",   notes_file,
         "--classification",  classification_str],
        capture_output=True, text=True,
        env={**os.environ},
    )

    # Cleanup
    os.unlink(diff_file)
    os.unlink(notes_file)

    if result.returncode != 0 and not result.stdout.strip():
        return {
            "decision": "request_human_review",
            "confidence": 0.0,
            "concerns": [f"Script error: {result.stderr[:300]}"],
            "summary": "LLM review script failed",
        }

    try:
        raw = result.stdout.strip()
        json_match = re.search(r'\{[\s\S]*\}', raw)
        return json.loads(json_match.group()) if json_match else {
            "decision": "request_human_review",
            "confidence": 0.0,
            "concerns": ["Could not parse LLM output"],
            "summary": raw[:200],
        }
    except Exception as e:
        return {
            "decision": "request_human_review",
            "confidence": 0.0,
            "concerns": [str(e)],
            "summary": "Parse error",
        }


# ── Render a single scenario result ──────────────────────────────────────────
def render_result(scenario: dict, classification: dict, review: dict | None):
    desc = scenario.get("_description", "")
    expected_keyword = ""
    if "APPROVE" in desc.upper():     expected_keyword = "approve"
    elif "BLOCKED" in desc.upper():   expected_keyword = "request_human_review"
    elif "ADVERSARIAL" in desc.upper(): expected_keyword = "adversarial"

    print(f"\n  {BOLD}Package:{RESET} {scenario['package_name']}  "
          f"{scenario['old_version']} → {scenario['new_version']}  "
          f"({scenario['bump_type']} bump, {scenario['ecosystem']})")
    print(f"  {BOLD}Description:{RESET} {desc}")

    # Classification result
    if classification["eligible"]:
        ok(f"Classification: ELIGIBLE — criteria file: {classification['criteria_file']}")
    else:
        fail(f"Classification: INELIGIBLE")
        for r in classification["reasons_ineligible"]:
            info(f"    → {r}")

    if review is None:
        info("  LLM review skipped (--no-llm or ineligible)")
        return

    # LLM result
    decision    = review.get("decision", "?")
    confidence  = float(review.get("confidence", 0))
    summary     = review.get("summary", "")
    concerns    = review.get("concerns", [])
    checklist   = review.get("checklist", {})

    if decision == "approve" and confidence >= 0.9:
        ok(f"LLM Review: APPROVE  (confidence: {confidence:.2f})")
    elif decision == "approve":
        warn(f"LLM Review: APPROVE but confidence too low ({confidence:.2f} < 0.90) → human review")
    else:
        fail(f"LLM Review: REQUEST HUMAN REVIEW  (confidence: {confidence:.2f})")

    info(f"    Summary: {summary}")

    if checklist:
        print(f"\n  {BOLD}Checklist:{RESET}")
        for k, v in checklist.items():
            icon = "✅" if v is True else "❌" if v is False else "⚠️ "
            print(f"    {icon} {k.replace('_', ' ')}")

    if concerns:
        print(f"\n  {BOLD}Concerns:{RESET}")
        for c_ in concerns:
            warn(f"    {c_}")

    # Check if adversarial injection was ignored
    if expected_keyword == "adversarial":
        injection_in_concerns = any(
            any(kw in str(c_).lower() for kw in ["inject", "override", "ignore", "system", "instruction"])
            for c_ in concerns
        )
        if injection_in_concerns:
            ok("Injection attempt detected and flagged in concerns ✓")
        else:
            warn("Injection attempt not explicitly flagged (check if decision was still correct)")


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Dependabot Sentinel demo runner")
    p.add_argument("--scenario", type=int, help="Run only this scenario number")
    p.add_argument("--no-llm", action="store_true", help="Skip LLM review (classify only)")
    p.add_argument("--list", action="store_true", help="List scenarios and exit")
    args = p.parse_args()

    scenarios = load_scenarios()

    if args.list:
        print(f"\n{BOLD}Available scenarios:{RESET}")
        for s in scenarios:
            print(f"  {s['_number']:>2}. {s['_file']}")
            print(f"      {DIM}{s['_description']}{RESET}")
        return

    if args.scenario:
        scenarios = [s for s in scenarios if s["_number"] == args.scenario]
        if not scenarios:
            print(f"No scenario #{args.scenario} found.")
            sys.exit(1)

    # Check API key if needed
    if not args.no_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"\n{RED}ANTHROPIC_API_KEY not set. Run with --no-llm to skip LLM review,\n"
              f"or set the key: export ANTHROPIC_API_KEY=sk-ant-...{RESET}")
        sys.exit(1)

    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  Dependabot Sentinel — Demo")
    print(f"  Running {len(scenarios)} scenario(s){'  [classify only]' if args.no_llm else '  [full pipeline]'}")
    print(f"{'═'*60}{RESET}")

    results_summary = []

    for scenario in scenarios:
        header(f"Scenario {scenario['_number']}: {scenario['pr_title']}")

        # 1. Classify
        info("Running classification...")
        t0 = time.time()
        classification = run_classify(scenario)
        info(f"Classification completed in {time.time()-t0:.1f}s")

        # 2. LLM Review
        review = None
        if not args.no_llm and classification["eligible"]:
            info("Running LLM review (calling Claude Opus)...")
            t0 = time.time()
            review = run_llm_review(scenario, classification)
            info(f"LLM review completed in {time.time()-t0:.1f}s")
        elif not classification["eligible"]:
            info("Skipping LLM review — PR not eligible")

        # 3. Render
        render_result(scenario, classification, review)

        # Collect summary
        if review:
            final_decision = review.get("decision")
            final_confidence = float(review.get("confidence", 0))
            if final_decision == "approve" and final_confidence < 0.9:
                final_decision = "request_human_review (low confidence)"
        elif not classification["eligible"]:
            final_decision = "request_human_review (ineligible)"
        else:
            final_decision = "skipped"

        results_summary.append({
            "scenario": scenario["_number"],
            "package": f"{scenario['package_name']} {scenario['old_version']}→{scenario['new_version']}",
            "decision": final_decision,
        })

    # Summary table
    header("Summary")
    for r in results_summary:
        decision = r["decision"]
        if decision == "approve":
            icon = GREEN + "✅ APPROVE              " + RESET
        elif decision == "skipped":
            icon = DIM  + "── skipped              " + RESET
        else:
            icon = RED  + "🛑 HUMAN REVIEW REQUIRED" + RESET
        print(f"  Scenario {r['scenario']}: {icon}  {r['package']}")

    print()


if __name__ == "__main__":
    main()
