# Review Criteria — Patch Version Bumps

Applies to: dependabot PRs classified as `patch` (e.g., 1.2.3 → 1.2.4)
Extends: `_base.md` (all base criteria apply)

Patch bumps are the lowest-risk class. By semver convention they should contain
only bug fixes and security patches, no API changes. However, not all maintainers
follow semver strictly, so we still inspect.

---

## Additional MUST PASS

- [ ] The version bump is strictly a patch increment (third number only, e.g., X.Y.Z → X.Y.Z+n)
- [ ] Release notes (if available) describe only: bug fixes, security patches, performance improvements, or internal refactors with no API surface change

## Additional MUST FAIL

- [ ] Release notes describe new features, new configuration options, or new APIs (this indicates a patch that violates semver — treat as minor)
- [ ] Release notes describe a behavior change even if framed as "fixing a bug" (e.g., "fixed incorrect validation that was previously too permissive" — this is a breaking behavior change)
- [ ] The version jump skips a number unexpectedly (e.g., 1.2.3 → 1.2.6 with no intermediate releases visible) without a clear explanation

## Additional INSPECT

- If this package is security-adjacent (auth, crypto, serialization, HTTP), note that in concerns even if approving
- If release notes are unavailable, lower confidence by 0.05
