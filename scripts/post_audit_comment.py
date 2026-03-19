#!/usr/bin/env python3
"""
post_audit_comment.py — Post a structured audit comment to the PR after auto-approval.

This creates a permanent, human-readable record on the PR itself.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def confidence_badge(confidence: float) -> str:
    """Generate a shields.io badge URL for the given confidence score (0.0–1.0)."""
    pct = int(confidence * 100)
    if confidence >= 0.9:
        color = "brightgreen"
    elif confidence >= 0.7:
        color = "yellow"
    elif confidence >= 0.5:
        color = "orange"
    else:
        color = "red"
    # shields.io static badge: spaces → %20, literal % → %25 in value
    url = f"https://img.shields.io/badge/sentinel%20confidence-{pct}%25-{color}?style=flat-square"
    return f"![sentinel confidence: {pct}%]({url})"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--pr-number", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--review-json", required=True)
    p.add_argument("--classification-json", required=True)
    return p.parse_args()


def main():
    args = parse_args()

    try:
        review = json.loads(args.review_json)
    except Exception:
        review = {"summary": "Could not parse review JSON", "confidence": 0, "checklist": {}, "concerns": []}

    try:
        classification = json.loads(args.classification_json)
    except Exception:
        classification = {}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build checklist markdown
    checklist_items = review.get("checklist", {})
    checklist_md = "\n".join(
        f"  - {'✅' if v is True else '❌' if v is False else '⚠️'} {k.replace('_', ' ')}"
        for k, v in checklist_items.items()
    )

    concerns_md = "\n".join(f"  - {c}" for c in review.get("concerns", [])) or "  - None"

    badge = confidence_badge(float(review.get("confidence", 0)))

    comment_body = f"""{badge}

### 🤖 Dependabot Sentinel Audit Log

**Decision:** `{review.get('decision', 'unknown')}` | **Confidence:** `{review.get('confidence', 0):.2f}`
**Timestamp:** {now}
**Package:** `{classification.get('package_name', '?')}` — `{classification.get('old_version', '?')}` → `{classification.get('new_version', '?')}`
**Bump type:** `{classification.get('bump_type', '?')}` | **Ecosystem:** `{classification.get('ecosystem', '?')}`

**Summary:** {review.get('summary', 'N/A')}

<details>
<summary>Review checklist</summary>

{checklist_md or '  (no checklist data)'}

</details>

<details>
<summary>Concerns flagged</summary>

{concerns_md}

</details>

<details>
<summary>Full review JSON</summary>

```json
{json.dumps(review, indent=2)}
```

</details>

---
*This approval was performed by Dependabot Sentinel. To block future auto-approvals on this repo, add the `sentinel-block` label or update `.github/review-criteria/critical-dependencies.yml`.*
"""

    result = subprocess.run(
        ["gh", "pr", "comment", args.pr_number,
         "--repo", args.repo,
         "--body", comment_body],
        capture_output=True, text=True, env=os.environ,
    )
    if result.returncode != 0:
        print(f"::warning::Could not post audit comment: {result.stderr}")
    else:
        print("Audit comment posted successfully.")


if __name__ == "__main__":
    main()
