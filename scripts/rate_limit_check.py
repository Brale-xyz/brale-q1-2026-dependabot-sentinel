#!/usr/bin/env python3
"""
rate_limit_check.py — Guard against runaway auto-approvals.

Counts recent Sentinel auto-approvals by scanning PR reviews from the
sentinel-bot account. If the count exceeds the threshold, exits non-zero
to block the approval and trigger alerting.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--window-minutes", type=int, default=60)
    p.add_argument("--max-approvals", type=int, default=10)
    p.add_argument("--sentinel-actor", default="sentinel-bot[bot]")
    return p.parse_args()


def get_recent_approvals(repo: str, window_minutes: int, sentinel_actor: str) -> list[dict]:
    """
    Fetch recent PRs and count approvals by the sentinel bot within the window.
    Uses the GitHub search API to find recently merged PRs.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Search for recently closed PRs
    result = subprocess.run(
        ["gh", "api",
         f"/repos/{repo}/pulls",
         "--method", "GET",
         "-f", "state=closed",
         "-f", "per_page=50",
         "-f", "sort=updated",
         "-f", "direction=desc",
         "--jq", f"[.[] | select(.merged_at != null and .merged_at >= \"{cutoff_str}\") | .number]"],
        capture_output=True, text=True, env=os.environ,
    )
    if result.returncode != 0:
        print(f"::warning::Could not fetch recent PRs: {result.stderr}")
        return []

    pr_numbers = json.loads(result.stdout or "[]")
    approvals = []

    for pr_num in pr_numbers[:20]:  # cap at 20 to avoid rate limits
        review_result = subprocess.run(
            ["gh", "api", f"/repos/{repo}/pulls/{pr_num}/reviews",
             "--jq", f"[.[] | select(.user.login == \"{sentinel_actor}\" and .state == \"APPROVED\")]"],
            capture_output=True, text=True, env=os.environ,
        )
        if review_result.returncode == 0:
            reviews = json.loads(review_result.stdout or "[]")
            for r in reviews:
                submitted_at = r.get("submitted_at", "")
                if submitted_at >= cutoff_str:
                    approvals.append({"pr": pr_num, "submitted_at": submitted_at})

    return approvals


def main():
    args = parse_args()

    print(f"Rate limit check: max {args.max_approvals} approvals per {args.window_minutes} minutes")

    approvals = get_recent_approvals(args.repo, args.window_minutes, args.sentinel_actor)
    count = len(approvals)

    print(f"Recent Sentinel approvals in window: {count}")
    for a in approvals:
        print(f"  PR #{a['pr']} approved at {a['submitted_at']}")

    if count >= args.max_approvals:
        print(f"::error::Rate limit exceeded: {count} approvals in the last {args.window_minutes} minutes "
              f"(max: {args.max_approvals}). Blocking auto-approval and requiring human review.")
        print(f"::error::This may indicate a supply-chain attack or misconfiguration. Investigate immediately.")
        sys.exit(1)

    print(f"Rate limit OK: {count}/{args.max_approvals} approvals in window.")


if __name__ == "__main__":
    main()
