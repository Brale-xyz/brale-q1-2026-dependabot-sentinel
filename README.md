# Dependabot Sentinel

Automated, LLM-reviewed auto-approval for dependabot PRs. Patch and minor version bumps
are reviewed by Claude Code against structured security criteria, then approved and
merged automatically — no human required for low-risk updates.

## Architecture

```
PR opened by dependabot[bot]
        │
        ▼
┌───────────────┐
│   CLASSIFY    │  Deterministic. Verifies commit sig, parses version bump,
│  (no LLM)    │  checks critical-deps list, verifies only manifests changed.
└──────┬────────┘
       │ eligible=true
       ▼
┌───────────────┐
│  WAIT FOR CI  │  Polls until all other status checks pass or fail.
└──────┬────────┘
       │ all green
       ▼
┌───────────────┐
│    REVIEW     │  Claude Code reads criteria files from BASE branch,
│ (Claude Opus) │  reviews diff + release notes, emits structured JSON.
└──────┬────────┘
       │ decision=approve, confidence>=0.9
       ▼
┌───────────────┐
│  RATE LIMIT   │  Blocks if >10 auto-approvals in last 60 minutes.
└──────┬────────┘
       │ ok
       ▼
┌───────────────┐
│  AUTO-APPROVE │  sentinel-bot approves + enables auto-merge + posts audit log.
└───────────────┘
```

Any step failure → "Request Human Review" comment on the PR.

## Setup

### 1. Create the sentinel-bot GitHub App

A dedicated GitHub App gives you a non-human approval identity with its own
audit trail, revocable independently of any person.

1. Go to **Settings → Developer Settings → GitHub Apps → New GitHub App**
2. Name: `sentinel-bot`, Homepage: your repo
3. Permissions: `Pull requests: Read & Write`, `Contents: Read`
4. Install the app on your repo
5. Generate an installation token and store as repo secret `SENTINEL_BOT_TOKEN`

### 2. Configure repository secrets

| Secret | Description |
|--------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key with access to Claude Opus |
| `SENTINEL_BOT_TOKEN` | GitHub App installation token for the sentinel-bot |

### 3. Configure branch protection

In **Settings → Branches → Branch protection rules** for your default branch:

- ✅ Require a pull request before merging
- ✅ Require approvals: 1
- ✅ Require status checks to pass: `Dependabot Sentinel / Classify PR`
- ✅ Allow auto-merge

### 4. Create the `sentinel-auto-approve` environment

In **Settings → Environments → New environment**:

- Name: `sentinel-auto-approve`
- Add protection rules if desired (e.g., required reviewers for the env itself)

### 5. Customize critical dependencies

Edit `.github/review-criteria/critical-dependencies.yml` to add packages
specific to your stack that should always require human review.

### 6. Add the `sentinel-block` label

Create a repo label named `sentinel-block`. Adding this label to any PR will
prevent Sentinel from auto-approving it.

## Criteria files

```
.github/review-criteria/
├── _base.md                     # Universal checks (all PRs)
├── _auto-approve-policy.md      # Policy document and audit reference
├── critical-dependencies.yml    # Never-auto-approve package list
├── dependabot-patch.md          # Additional checks for patch bumps
└── dependabot-minor.md          # Additional checks for minor bumps
```

**Security note:** Criteria files are always read from the **base branch**, never
from the PR branch. This prevents an attacker from weakening review criteria
by including a modified criteria file in a dependabot PR.

## Confidence thresholds

| Bump type | Min confidence to auto-approve |
|-----------|-------------------------------|
| patch | 0.90 |
| minor | 0.90 (harder to reach — see criteria) |
| major | Never auto-approved |

## Rate limiting

By default: max 10 auto-approvals per 60 minutes. Adjust in the workflow:

```yaml
- name: Rate limit check
  run: |
    python3 scripts/rate_limit_check.py \
      --window-minutes 60 \
      --max-approvals 10
```

An alert fires if the rate limit is exceeded — treat this as a potential
supply-chain incident.

## Overrides

- Add label `sentinel-block` to force human review on a specific PR
- Edit `critical-dependencies.yml` to permanently require human review for a package
- Disable the workflow entirely via Actions settings
