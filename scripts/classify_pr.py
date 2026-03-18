#!/usr/bin/env python3
"""
classify_pr.py — Deterministic pre-filter for Dependabot Sentinel.

Parses the PR title/body to extract package info, validates the bump type,
checks against the critical-dependencies list, and verifies only
manifest/lockfile files were changed. Writes GitHub Actions outputs.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import yaml
from pathlib import Path

# Files that are acceptable to change in a dependabot PR.
# Anything not matching these patterns triggers an ineligibility flag.
ALLOWED_FILE_PATTERNS = [
    # Python
    r"requirements.*\.txt$",
    r"Pipfile(\.lock)?$",
    r"pyproject\.toml$",
    r"setup\.cfg$",
    r"poetry\.lock$",
    # JavaScript / Node
    r"package\.json$",
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
    # Ruby
    r"Gemfile(\.lock)?$",
    r".*\.gemspec$",
    # Go
    r"go\.(mod|sum)$",
    # Rust
    r"Cargo\.(toml|lock)$",
    # Java / Maven / Gradle
    r"pom\.xml$",
    r"build\.gradle(\.kts)?$",
    r"gradle-wrapper\.properties$",
    r"gradle/libs\.versions\.toml$",
    # .NET
    r".*\.csproj$",
    r".*\.fsproj$",
    r"packages\.lock\.json$",
    # GitHub Actions
    r"\.github/workflows/.*\.ya?ml$",   # dependabot updates action versions too
]

# Patterns to detect major version bumps in the PR title
DEPENDABOT_TITLE_RE = re.compile(
    r"bump (?P<package>.+?) from (?P<old>[\d.]+(?:[-+][^\s]+)?) to (?P<new>[\d.]+(?:[-+][^\s]+)?)",
    re.IGNORECASE,
)

SEMVER_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--pr-title", required=True)
    p.add_argument("--pr-number", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--base-sha", required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--sig-ok", required=True)
    return p.parse_args()


def load_critical_deps() -> dict:
    crit_path = Path(".github/review-criteria/critical-dependencies.yml")
    if not crit_path.exists():
        print("::warning::critical-dependencies.yml not found, skipping critical dep check")
        return {}
    with open(crit_path) as f:
        return yaml.safe_load(f) or {}


def get_changed_files(repo: str, pr_number: str) -> list[dict]:
    result = subprocess.run(
        ["gh", "api", f"/repos/{repo}/pulls/{pr_number}/files",
         "--jq", "[.[] | {filename: .filename, status: .status}]"],
        capture_output=True, text=True, env=os.environ,
    )
    if result.returncode != 0:
        print(f"::error::Failed to fetch PR files: {result.stderr}")
        sys.exit(1)
    return json.loads(result.stdout or "[]")


def is_allowed_file(filename: str) -> bool:
    return any(re.search(pat, filename) for pat in ALLOWED_FILE_PATTERNS)


def classify_bump(old: str, new: str) -> str:
    om = SEMVER_RE.match(old)
    nm = SEMVER_RE.match(new)
    if not om or not nm:
        return "unknown"
    if nm.group("major") != om.group("major"):
        return "major"
    if nm.group("minor") != om.group("minor"):
        return "minor"
    return "patch"


def detect_ecosystem(files: list[dict]) -> str:
    filenames = [f["filename"] for f in files]
    if any("package.json" in fn or "package-lock.json" in fn or "yarn.lock" in fn for fn in filenames):
        return "npm"
    if any(fn.startswith("requirements") or "Pipfile" in fn or "pyproject.toml" in fn for fn in filenames):
        return "pip"
    if any("go.mod" in fn or "go.sum" in fn for fn in filenames):
        return "go"
    if any("Cargo" in fn for fn in filenames):
        return "cargo"
    if any("Gemfile" in fn for fn in filenames):
        return "gem"
    if any("pom.xml" in fn or "build.gradle" in fn for fn in filenames):
        return "maven"
    return "unknown"


def is_critical_dep(package: str, ecosystem: str, critical_deps: dict) -> bool:
    deps = critical_deps.get(ecosystem, [])
    # Match exact name or prefix (e.g., "babel" matches "@babel/core")
    return any(
        package == dep or package.startswith(dep + "/") or package.endswith("/" + dep)
        for dep in deps
    )


def write_outputs(data: dict):
    output_file = os.environ.get("GITHUB_OUTPUT", "/dev/stdout")
    with open(output_file, "a") as f:
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value).replace("%", "%25").replace("\n", "%0A")
            f.write(f"{key}={value}\n")


def main():
    args = parse_args()
    reasons_ineligible = []

    # 1. Commit signature check
    if args.sig_ok.lower() != "true":
        reasons_ineligible.append("commit signature not verified")

    # 2. Parse PR title
    m = DEPENDABOT_TITLE_RE.search(args.pr_title)
    if not m:
        reasons_ineligible.append(f"PR title does not match dependabot format: {args.pr_title!r}")
        write_outputs({"eligible": "false"})
        print(f"::notice::Ineligible: {'; '.join(reasons_ineligible)}")
        sys.exit(0)

    package_name = m.group("package").strip()
    old_version = m.group("old").strip()
    new_version = m.group("new").strip()

    # 3. Classify bump type
    bump_type = classify_bump(old_version, new_version)
    print(f"Package: {package_name}, {old_version} → {new_version}, bump: {bump_type}")

    if bump_type == "major":
        reasons_ineligible.append(f"major version bump: {old_version} → {new_version}")
    if bump_type == "unknown":
        reasons_ineligible.append(f"could not parse version bump: {old_version} → {new_version}")

    # 4. Get changed files
    changed_files = get_changed_files(args.repo, args.pr_number)
    bad_files = [f["filename"] for f in changed_files if not is_allowed_file(f["filename"])]
    if bad_files:
        reasons_ineligible.append(f"unexpected files changed: {bad_files}")

    # 5. Detect ecosystem
    ecosystem = detect_ecosystem(changed_files)

    # 6. Critical dependency check
    critical_deps = load_critical_deps()
    if is_critical_dep(package_name, ecosystem, critical_deps):
        reasons_ineligible.append(f"{package_name} is in critical-dependencies list")

    # 7. Determine criteria file
    criteria_file = f"dependabot-{bump_type}.md" if bump_type in ("patch", "minor") else "_base.md"

    # 8. Build classification JSON
    classification = {
        "package_name": package_name,
        "old_version": old_version,
        "new_version": new_version,
        "bump_type": bump_type,
        "ecosystem": ecosystem,
        "changed_files": [f["filename"] for f in changed_files],
        "sig_ok": args.sig_ok == "true",
        "eligible": len(reasons_ineligible) == 0,
        "ineligible_reasons": reasons_ineligible,
    }

    eligible = len(reasons_ineligible) == 0

    if not eligible:
        print(f"::notice::PR ineligible for auto-approve: {'; '.join(reasons_ineligible)}")
    else:
        print(f"::notice::PR eligible for auto-approve review: {bump_type} bump of {package_name}")

    write_outputs({
        "eligible": "true" if eligible else "false",
        "bump_type": bump_type,
        "package_name": package_name,
        "old_version": old_version,
        "new_version": new_version,
        "criteria_file": criteria_file,
        "classification_json": classification,
    })


if __name__ == "__main__":
    main()
