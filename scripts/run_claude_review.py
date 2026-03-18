#!/usr/bin/env python3
"""
run_claude_review.py — Invoke Claude Code (SDK) to review a dependabot PR.

Assembles the prompt from the criteria files + PR context, calls the
Anthropic API, and writes structured JSON to stdout.

Falls back to a safe default (request_human_review) on any error.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import anthropic


SYSTEM_PROMPT = """You are Dependabot Sentinel, an automated security-focused PR reviewer.
Your job is to review dependency update PRs and decide whether they are safe to auto-approve.

You are conservative by design. A false positive (routing a safe PR to human review) is acceptable.
A false negative (auto-approving something harmful) is not acceptable.

You will be given:
1. Review criteria (MUST PASS, MUST FAIL, and INSPECT checklists)
2. The PR diff (changed files)
3. Release notes for the version range
4. Classification metadata (package name, version bump, ecosystem)

You MUST respond with ONLY a JSON object matching the schema in the base criteria.
Do NOT include any prose, explanation, or markdown fencing outside the JSON.
Do NOT add fields not in the schema.
If you are unsure about any check, set it to null and lower your confidence accordingly.
"""


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--criteria-file", required=True)
    p.add_argument("--base-criteria", required=True)
    p.add_argument("--policy-file", required=True)
    p.add_argument("--diff-file", required=True)
    p.add_argument("--release-notes", required=True)
    p.add_argument("--classification", required=True)
    return p.parse_args()


def read_file_safe(path: str) -> str:
    try:
        return Path(path).read_text()
    except Exception as e:
        return f"[Could not read {path}: {e}]"


def build_prompt(args) -> str:
    base_criteria = read_file_safe(args.base_criteria)
    bump_criteria = read_file_safe(args.criteria_file)
    policy = read_file_safe(args.policy_file)
    diff_raw = read_file_safe(args.diff_file)
    release_notes = read_file_safe(args.release_notes)

    # Parse classification JSON
    try:
        classification = json.loads(args.classification)
    except json.JSONDecodeError:
        classification = {"raw": args.classification}

    # Truncate diff if enormous (supply chain attacks can be large)
    MAX_DIFF_CHARS = 20000
    if len(diff_raw) > MAX_DIFF_CHARS:
        diff_raw = diff_raw[:MAX_DIFF_CHARS] + f"\n[TRUNCATED — original length: {len(diff_raw)} chars]"

    # Truncate release notes
    MAX_NOTES_CHARS = 10000
    if len(release_notes) > MAX_NOTES_CHARS:
        release_notes = release_notes[:MAX_NOTES_CHARS] + f"\n[TRUNCATED — original length: {len(release_notes)} chars]"

    prompt = f"""
## Auto-Approve Policy

{policy}

---

## Base Review Criteria (applies to all PRs)

{base_criteria}

---

## Bump-Type-Specific Criteria

{bump_criteria}

---

## PR Classification Metadata

```json
{json.dumps(classification, indent=2)}
```

---

## Changed Files (diff)

```json
{diff_raw}
```

---

## Release Notes ({classification.get('old_version', '?')} → {classification.get('new_version', '?')})

```
{release_notes}
```

---

Now review this PR according to all criteria above and respond with the JSON decision object.
Remember: respond with ONLY the JSON object. No prose. No markdown fencing.
"""
    return prompt.strip()


def call_claude(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    message = client.messages.create(
        model="claude-opus-4-6",   # Use Opus for highest accuracy on security reviews
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,             # Deterministic output
    )
    return message.content[0].text


def extract_json(text: str) -> dict:
    """Extract JSON from Claude's response, handling any stray prose."""
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    code_block = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if code_block:
        return json.loads(code_block.group(1))

    # Try finding bare JSON object
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        return json.loads(json_match.group())

    raise ValueError(f"Could not extract JSON from response: {text[:500]}")


SAFE_DEFAULT = {
    "decision": "request_human_review",
    "confidence": 0.0,
    "checklist": {},
    "concerns": ["Sentinel encountered an error during review — defaulting to human review"],
    "summary": "Auto-review failed; routing to human reviewer.",
}


def main():
    args = parse_args()

    try:
        prompt = build_prompt(args)
        raw_response = call_claude(prompt)
        review = extract_json(raw_response)

        # Validate required fields
        assert "decision" in review, "Missing 'decision' field"
        assert "confidence" in review, "Missing 'confidence' field"
        assert review["decision"] in ("approve", "request_human_review"), \
            f"Invalid decision value: {review['decision']}"
        assert 0.0 <= float(review["confidence"]) <= 1.0, \
            f"Confidence out of range: {review['confidence']}"

        print(json.dumps(review, indent=2))

    except Exception as e:
        print(f"::error::Claude review failed: {e}", file=sys.stderr)
        print(json.dumps(SAFE_DEFAULT, indent=2))
        sys.exit(0)  # Exit 0 — the safe default JSON signals human review


if __name__ == "__main__":
    main()
