# Base Review Criteria — All Dependabot PRs

These criteria apply to every PR reviewed by Dependabot Sentinel, regardless of bump type.
Bump-type-specific criteria files add to (not replace) these.

---

## Context You Will Receive

You will be given:
- `classification`: structured JSON describing the PR (package, bump type, ecosystem, etc.)
- `diff`: JSON array of changed files with patches
- `release_notes`: text fetched from the upstream package

---

## Universal MUST PASS (all required for auto-approve)

- [ ] Only manifest files and lockfiles are modified (no `.py`, `.js`, `.ts`, `.go`, `.rs`, `.rb`, `.java`, `.c`, `.cpp`, `.sh`, `.tf`, `.yml`/`.yaml` source files changed)
- [ ] The diff matches what would be expected for the stated version bump (version string changes, hash updates in lockfile — nothing else)
- [ ] No new top-level transitive dependencies are introduced by the bump
- [ ] Package name in diff matches the package name in the classification metadata
- [ ] CI status checks have passed (verified by the workflow, not by you)

## Universal MUST FAIL (any one blocks auto-approve)

- [ ] Any source code file is modified
- [ ] A file outside the expected manifest/lockfile paths is modified
- [ ] The release notes mention **breaking changes**, **migration required**, **API changes**, or **deprecation**
- [ ] The release notes mention a security advisory being **introduced** (as opposed to fixed) in the new version
- [ ] The package name or version numbers in the diff do not match the classification metadata
- [ ] The diff contains content that appears to be executable code, eval, or script injection (supply chain red flag)
- [ ] Release notes mention a change in package ownership or maintainer in the bump range

## Universal INSPECT (examine but not automatic gates)

- Does the changelog have any unusual gaps (e.g., classified as patch but release notes describe new features)?
- Are there any new peer dependency requirements?
- Does the diff size seem unexpectedly large for the stated version bump?

---

## Output Format

**You MUST return a single JSON object and nothing else.** No prose. No markdown. No explanation outside the JSON.

```json
{
  "decision": "approve" | "request_human_review",
  "confidence": 0.0,
  "checklist": {
    "only_manifests_changed": true | false | null,
    "diff_matches_version_bump": true | false | null,
    "no_new_transitive_deps": true | false | null,
    "no_breaking_changes_in_notes": true | false | null,
    "no_new_security_issues": true | false | null,
    "no_ownership_change": true | false | null,
    "no_source_files_modified": true | false | null
  },
  "concerns": [],
  "summary": "One sentence explanation of the decision."
}
```

**Confidence scoring:**
- 1.0 = All checks pass with strong evidence, release notes confirm no issues
- 0.9 = All checks pass, minor uncertainty (e.g., release notes unavailable)
- 0.7–0.89 = Some checks inconclusive, issues possible but not confirmed
- < 0.7 = Clear concerns or failed checks — always `request_human_review`

**If you cannot confidently evaluate any required check, set `decision` to `request_human_review`.**
**If you are uncertain, err toward `request_human_review`. False positives (unnecessary human reviews) are acceptable. False negatives (auto-approving something harmful) are not.**
