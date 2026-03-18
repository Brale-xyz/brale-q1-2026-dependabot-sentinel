# Review Criteria — Minor Version Bumps

Applies to: dependabot PRs classified as `minor` (e.g., 1.2.x → 1.3.0)
Extends: `_base.md` (all base criteria apply)

Minor bumps carry more risk than patches. Semver permits new features in minor
releases, and maintainers sometimes introduce subtle breaking changes. Apply
more scrutiny here. Confidence thresholds are harder to reach.

---

## Additional MUST PASS

- [ ] Release notes confirm backward compatibility (explicitly stated OR evident from the nature of changes)
- [ ] No new required configuration, environment variables, or initialization changes are mentioned
- [ ] New features introduced are additive only (new functions/methods, not changed signatures)
- [ ] If the package has a CHANGELOG, the entry for the new version is consistent with a minor bump (no `BREAKING`, `DEPRECATED`, or migration sections)

## Additional MUST FAIL

- [ ] Release notes contain any of: `BREAKING`, `deprecated`, `removed`, `migration`, `upgrade guide`, `no longer supported`
- [ ] Release notes describe changes to default behavior (even if framed as improvements)
- [ ] New required peer dependencies are introduced
- [ ] The minor version is a `0.x` release (e.g., 0.3.0 → 0.4.0): semver guarantees do NOT apply for pre-1.0 packages — route to human
- [ ] The package is a framework, ORM, auth library, or infrastructure tool — minor bumps for these always require human review (check `critical-dependencies.yml`)

## Additional INSPECT

- How large is the diff between versions? For a minor bump, a diff of hundreds of lines in the manifest/lockfile is worth noting
- Is this a widely-used package with a history of semver violations? (Well-known examples: `moment`, legacy `webpack` plugins)
- Are there new transitive dependencies? List them in concerns if present

## Confidence Guidance for Minor Bumps

Minor bumps should rarely exceed 0.92 confidence. The threshold is still 0.9, but
be conservative. If release notes are unavailable for a minor bump, maximum
confidence is 0.80 — do not approve without release notes for minor bumps.
