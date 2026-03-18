# Dependabot Sentinel — Auto-Approve Policy

**Last updated:** 2026-03-18
**Owner:** Security Engineering

This document defines what the Sentinel system will and will not auto-approve.
It exists for auditability and to serve as the source of truth for the review criteria files.

---

## What Can Be Auto-Approved

A PR may be auto-approved only when ALL of the following are true:

1. The PR was opened by `dependabot[bot]` with a verified commit signature
2. The version bump is `patch` or `minor` (never `major`)
3. The package is NOT in `critical-dependencies.yml`
4. Only manifest and lockfile files are changed
5. All repository CI checks have passed
6. Claude Code review returns `decision: approve` with `confidence >= 0.9`
7. The rate limit has not been exceeded (10 auto-approvals per 60 minutes per repo)

## What Will Never Be Auto-Approved

- Major version bumps
- Packages in `critical-dependencies.yml`
- PRs where any source code file is modified
- PRs with unverified commit signatures
- PRs where release notes describe breaking changes, migrations, or behavior changes
- Pre-1.0 minor version bumps
- Any PR where Claude Code confidence is below 0.9 for any reason
- Any PR where the rate limiter has been triggered

## Accountability

Every auto-approval is:
- Recorded as a review comment with full audit JSON on the PR
- Stored as a GitHub Actions artifact for 90 days
- Performed by the `sentinel-bot` GitHub App, not by a human account

## Overrides

A human reviewer may override a Sentinel decision at any time by:
- Manually approving a PR that Sentinel declined
- Closing a PR that Sentinel approved (before merge completes)
- Adding the label `sentinel-block` to force human review on any PR

## Changing This Policy

Changes to this file or any criteria file require:
- PR review by at least one Security Engineering team member
- The change must land on the default branch before it takes effect
  (Sentinel always reads criteria from the base branch, never the PR branch)
