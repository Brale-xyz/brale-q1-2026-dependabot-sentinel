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
import time
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
5. Repository source code (when available) for code impact analysis

Key reasoning rules:
- When evaluating a bump from version A to version Z, only the NET delta from A to Z matters.
  Intermediate versions (A+1, A+2, ..., Z-1) are never installed. If a behavior or feature was
  introduced in an intermediate version and then FULLY REVERTED before Z, the net effect is zero
  and it must NOT count as a concern. Explicitly add it to code_impact.mitigated.
- When release notes mention deprecated or removed APIs, check the provided source code.
  If the affected API does not appear in our codebase, add it to code_impact.mitigated and
  do NOT let it block approval.
- Python version support drops (e.g., "dropped Python 3.7") are only relevant if our project
  targets that Python version. Check .python-version, pyproject.toml, or CI config in the
  provided source. If our project targets a higher version, add it to code_impact.mitigated.

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
    p.add_argument("--source-file", default=None,
                   help="Concatenated repo source files for code impact analysis")
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

    # Load repo source for code impact analysis
    source_section = ""
    if args.source_file:
        source_code = read_file_safe(args.source_file)
        MAX_SOURCE_CHARS = 15000
        if len(source_code) > MAX_SOURCE_CHARS:
            source_code = source_code[:MAX_SOURCE_CHARS] + f"\n[TRUNCATED — original length: {len(source_code)} chars]"
        if source_code.strip() and not source_code.startswith("[Could not read"):
            source_section = f"""---

## Repository Source Code (for code impact analysis)

The following is the application source code of this repository. For each concern you identify about deprecated, removed, or changed APIs:
1. Search this source code for the specific function/class/pattern names mentioned
2. If found: add to `code_impact.affected` with the file path and matching pattern
3. If not found: add to `code_impact.mitigated` with a clear note that it is not used in our code
4. Set `breaking_changes_not_used_in_our_code` to `true` if ALL breaking change concerns are mitigated (not found in source), `false` if any are found, `null` if there are no breaking change concerns

```
{source_code}
```
"""

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

{source_section}
Now review this PR according to all criteria above and respond with the JSON decision object.
Remember: respond with ONLY the JSON object. No prose. No markdown fencing.
"""
    return prompt.strip()


def call_claude(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    max_attempts = 4
    base_delay = 15  # seconds

    for attempt in range(1, max_attempts + 1):
        try:
            message = client.messages.create(
                model="claude-opus-4-6",   # Use Opus for highest accuracy on security reviews
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,             # Deterministic output
            )
            return message.content[0].text

        except anthropic.APIStatusError as e:
            # 529 = overloaded, 529/500/503 are all transient — retry with backoff
            if e.status_code in (529, 500, 503) and attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))  # 15s, 30s, 60s
                print(
                    f"::warning::Anthropic API returned {e.status_code} (attempt {attempt}/{max_attempts}). "
                    f"Retrying in {delay}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raise  # Non-retryable or out of attempts

        except anthropic.APIConnectionError as e:
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                print(
                    f"::warning::Anthropic API connection error (attempt {attempt}/{max_attempts}). "
                    f"Retrying in {delay}s: {e}",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raise

    raise RuntimeError("Exhausted all retry attempts calling Anthropic API")


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
