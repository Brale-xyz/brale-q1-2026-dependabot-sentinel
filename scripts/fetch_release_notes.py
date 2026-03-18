#!/usr/bin/env python3
"""
fetch_release_notes.py — Fetch release notes for a dependency version bump.

Supports: npm, PyPI (with GitHub releases), Go modules, crates.io.
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

    changelog_url = pkg.get("repository", {})
    if isinstance(changelog_url, dict):
        repo_url = changelog_url.get("url", "")
        if repo_url:
            lines.append(f"Repository: {repo_url}\n")

    times = pkg.get("time", {})
    all_versions = list(pkg.get("versions", {}).keys())
    for v in all_versions:
        if _version_in_range(v, old_ver, new_ver):
            ts = times.get(v, "")
            lines.append(f"\n## {v} ({ts})")
            lines.append("(changelog not available via npm registry; check repository releases)")

    return "\n".join(lines) or "(no release notes available)"


def fetch_github_releases(repo: str, old_ver: str, new_ver: str) -> list:
    """Fetch GitHub releases for versions between old (exclusive) and new (inclusive)."""
    url = f"https://api.github.com/repos/{repo}/releases?per_page=50"
    data = fetch_url(url)
    if not data:
        return []
    try:
        releases = json.loads(data)
    except Exception:
        return []

    lines = []
    for release in releases:
        tag = release.get("tag_name", "")
        ver = tag.lstrip("v")
        if _version_in_range(ver, old_ver, new_ver):
            body = (release.get("body") or "").strip() or "(no release description)"
            pub = release.get("published_at", "N/A")
            lines.append(f"\n### {tag} ({pub})")
            # Truncate very long release notes to keep prompt size reasonable
            if len(body) > 3000:
                body = body[:3000] + "\n... (truncated, see full release on GitHub)"
            lines.append(body)
    return lines


def _extract_github_repo(info: dict) -> Optional[str]:
    """Extract a github.com/owner/repo string from PyPI package info."""
    # Check project_urls first (more reliable)
    project_urls = info.get("project_urls") or {}
    candidates = list(project_urls.values())
    # Also check home_page and bugtrack_url
    for field in ("home_page", "bugtrack_url", "docs_url"):
        val = info.get(field) or ""
        if val:
            candidates.append(val)

    for url in candidates:
        if not url:
            continue
        match = re.search(r"github\.com/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)", url)
        if match:
            repo = match.group(1).rstrip("/")
            # Strip .git suffix if present
            if repo.endswith(".git"):
                repo = repo[:-4]
            return repo
    return None


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
        f"# {package} (PyPI) release notes ({old_ver} → {new_ver})",
        f"Summary: {info.get('summary', 'N/A')}",
        f"Requires Python: {info.get('requires_python', 'not specified')}",
        f"License: {info.get('license', 'N/A')}",
        "",
    ]

    # List versions in range with upload timestamps
    releases = pkg.get("releases", {})
    in_range = []
    for v, files in releases.items():
        if _version_in_range(v, old_ver, new_ver) and files:
            upload_time = files[0].get("upload_time", "unknown")
            in_range.append((v, upload_time))
    if in_range:
        lines.append("## Versions in this bump range:")
        for v, ts in sorted(in_range):
            lines.append(f"  - {v} (uploaded: {ts})")
        lines.append("")

    # Fetch actual release notes from GitHub
    github_repo = _extract_github_repo(info)
    if github_repo:
        lines.append(f"## GitHub release notes (from {github_repo}):")
        gh_lines = fetch_github_releases(github_repo, old_ver, new_ver)
        if gh_lines:
            lines.extend(gh_lines)
        else:
            lines.append("(no GitHub releases found for versions in this range)")
            # Still note the repo so Claude can reference it
            lines.append(f"Full releases at: https://github.com/{github_repo}/releases")
    else:
        lines.append("(could not determine GitHub repository from PyPI metadata)")

    return "\n".join(lines) or "(no release notes available)"


def fetch_hex(package: str, old_ver: str, new_ver: str) -> str:
    """Fetch release notes for Elixir/Erlang packages from hex.pm."""
    url = f"https://hex.pm/api/packages/{package}"
    data = fetch_url(url)
    if not data:
        return ""
    try:
        pkg = json.loads(data)
    except Exception:
        return ""

    meta = pkg.get("meta", {})
    links = meta.get("links", {})

    lines = [
        f"# {package} (hex.pm) release notes ({old_ver} → {new_ver})",
        f"Description: {meta.get('description', 'N/A')}",
        f"Licenses: {', '.join(meta.get('licenses', [])) or 'N/A'}",
    ]
    for label, link_url in links.items():
        lines.append(f"{label}: {link_url}")
    lines.append("")

    # List in-range releases
    in_range = []
    for release in pkg.get("releases", []):
        v = release.get("version", "")
        if _version_in_range(v, old_ver, new_ver):
            in_range.append((v, release.get("inserted_at", "unknown")))
    if in_range:
        lines.append("## Versions in this bump range:")
        for v, ts in sorted(in_range):
            lines.append(f"  - {v} (published: {ts})")
        lines.append("")

    # Try to fetch GitHub release notes from the links
    github_repo = None
    for link_url in links.values():
        match = re.search(r"github\.com/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)", link_url or "")
        if match:
            github_repo = match.group(1).rstrip("/").rstrip(".git")
            break

    if github_repo:
        lines.append(f"## GitHub release notes (from {github_repo}):")
        gh_lines = fetch_github_releases(github_repo, old_ver, new_ver)
        if gh_lines:
            lines.extend(gh_lines)
        else:
            lines.append("(no GitHub releases found for versions in this range)")
            lines.append(f"Full releases at: https://github.com/{github_repo}/releases")
    else:
        lines.append("(no GitHub repository link found in hex.pm metadata)")

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
    """Check if v is between old (exclusive) and new (inclusive)."""
    try:
        from packaging.version import Version
        return Version(old) < Version(v) <= Version(new)
    except Exception:
        return v == new


def main():
    args = parse_args()
    ecosystem = args.ecosystem.lower()

    # For auto-detection, infer from package name heuristics
    if ecosystem == "auto":
        if args.package.startswith("github.com/") or args.package.startswith("golang.org/"):
            ecosystem = "go"
        else:
            ecosystem = "unknown"

    notes = ""

    # Dispatch to the right fetcher based on ecosystem.
    # Explicit ecosystems never fall through to wrong registries (e.g. pip → npm).
    if ecosystem in ("pip", "pypi"):
        notes = fetch_pypi(args.package, args.old_version, args.new_version)
    elif ecosystem in ("npm", "yarn", "pnpm", "typescript"):
        # TypeScript packages are npm packages (@types/*, etc.)
        notes = fetch_npm(args.package, args.old_version, args.new_version)
    elif ecosystem in ("cargo", "rust"):
        notes = fetch_crates(args.package, args.old_version, args.new_version)
    elif ecosystem in ("mix", "hex", "elixir"):
        notes = fetch_hex(args.package, args.old_version, args.new_version)
    else:
        # Unknown — no reliable heuristic, try registries in order of specificity
        notes = fetch_pypi(args.package, args.old_version, args.new_version)
        if not notes.strip():
            notes = fetch_npm(args.package, args.old_version, args.new_version)
        if not notes.strip():
            notes = fetch_crates(args.package, args.old_version, args.new_version)
        if not notes.strip():
            notes = fetch_hex(args.package, args.old_version, args.new_version)

    if not notes.strip():
        notes = f"(release notes not available for {args.package} {args.old_version}→{args.new_version})"

    print(notes)


if __name__ == "__main__":
    main()
