#!/usr/bin/env python3
"""
fetch_release_notes.py — Fetch release notes for a dependency version bump.

Supports: npm, PyPI, Go modules (pkg.go.dev), crates.io.
Prints notes to stdout. Errors are non-fatal — missing notes reduce
Claude's confidence but don't block the review.
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from typing import Optional


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--package", required=True)
    p.add_argument("--old-version", required=True)
    p.add_argument("--new-version", required=True)
    p.add_argument("--ecosystem", default="auto")
    return p.parse_args()


def fetch_url(url: str, timeout: int = 10) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dependabot-sentinel/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[fetch_release_notes] Could not fetch {url}: {e}", file=sys.stderr)
        return None


def fetch_npm(package: str, old_ver: str, new_ver: str) -> str:
    url = f"https://registry.npmjs.org/{package}"
    data = fetch_url(url)
    if not data:
        return ""
    try:
        pkg = json.loads(data)
    except Exception:
        return ""

    lines = [f"# {package} release notes ({old_ver} → {new_ver})\n"]

    # Get all versions in range (inclusive of new, post old)
    all_versions = list(pkg.get("versions", {}).keys())
    changelog_url = pkg.get("repository", {})
    if isinstance(changelog_url, dict):
        repo_url = changelog_url.get("url", "")
        if repo_url:
            lines.append(f"Repository: {repo_url}\n")

    # Pull time info
    times = pkg.get("time", {})
    for v in all_versions:
        if _version_in_range(v, old_ver, new_ver):
            ts = times.get(v, "")
            lines.append(f"\n## {v} ({ts})")
            # npm doesn't provide changelogs in registry — note the limitation
            lines.append("(changelog not available via npm registry; check repository releases)")

    return "\n".join(lines) or "(no release notes available)"


def fetch_pypi(package: str, old_ver: str, new_ver: str) -> str:
    url = f"https://pypi.org/pypi/{package}/json"
    data = fetch_url(url)
    if not data:
        return ""
    try:
        pkg = json.loads(data)
    except Exception:
        return ""

    info = pkg.get("info", {})
    lines = [
        f"# {package} release notes ({old_ver} → {new_ver})",
        f"Project URL: {info.get('project_url', 'N/A')}",
        f"Home page: {info.get('home_page', 'N/A')}",
        f"Description summary: {info.get('summary', 'N/A')}",
        "",
        "Note: Full changelog typically in repository. Check project_url above.",
        f"Current version: {info.get('version')}",
        f"Requires Python: {info.get('requires_python', 'not specified')}",
        "",
    ]

    releases = pkg.get("releases", {})
    for v, files in releases.items():
        if _version_in_range(v, old_ver, new_ver) and files:
            upload_time = files[0].get("upload_time", "")
            lines.append(f"## {v} (uploaded: {upload_time})")

    return "\n".join(lines) or "(no release notes available)"


def fetch_crates(package: str, old_ver: str, new_ver: str) -> str:
    url = f"https://crates.io/api/v1/crates/{package}/versions"
    data = fetch_url(url)
    if not data:
        return ""
    try:
        pkg = json.loads(data)
    except Exception:
        return ""

    lines = [f"# {package} (crates.io) release notes ({old_ver} → {new_ver})"]
    for v in pkg.get("versions", []):
        num = v.get("num", "")
        if _version_in_range(num, old_ver, new_ver):
            lines.append(f"\n## {num} (published: {v.get('created_at', 'N/A')})")
            if v.get("yanked"):
                lines.append("⚠️  THIS VERSION WAS YANKED")

    return "\n".join(lines) or "(no release notes available)"


def _version_in_range(v: str, old: str, new: str) -> bool:
    """Very naive: check if v is between old (exclusive) and new (inclusive)."""
    try:
        from packaging.version import Version
        return Version(old) < Version(v) <= Version(new)
    except Exception:
        return v == new


def detect_ecosystem(package: str) -> str:
    if package.startswith("github.com/") or package.startswith("golang.org/"):
        return "go"
    if "/" in package and not package.startswith("@"):
        return "go"  # rough heuristic
    return "unknown"


def main():
    args = parse_args()
    ecosystem = args.ecosystem

    if ecosystem == "auto":
        # Try to infer from package name
        if args.package.startswith("@") or re.match(r"^[a-z0-9_\-]+$", args.package):
            # Could be npm or pip — try both, first responder wins
            ecosystem = "unknown"
        elif args.package.startswith("github.com/"):
            ecosystem = "go"
        else:
            ecosystem = "unknown"

    notes = ""

    if ecosystem in ("npm", "unknown"):
        notes = fetch_npm(args.package, args.old_version, args.new_version)

    if not notes.strip() and ecosystem in ("pip", "pypi", "unknown"):
        notes = fetch_pypi(args.package, args.old_version, args.new_version)

    if not notes.strip() and ecosystem in ("cargo", "rust", "unknown"):
        notes = fetch_crates(args.package, args.old_version, args.new_version)

    if not notes.strip():
        notes = f"(release notes not available for {args.package} {args.old_version}→{args.new_version})"

    print(notes)


if __name__ == "__main__":
    main()
