# Sentinel Demo

Runs the full pipeline locally against mock PR data — no GitHub repo, no real dependabot PRs needed.

## Setup (one time)

```bash
cd brale-q1-2026-dependabot-sentinel
pip install anthropic pyyaml packaging
export ANTHROPIC_API_KEY=sk-ant-...
```

## Running the demo

```bash
# Full pipeline — all 4 scenarios
python3 demo/run_demo.py

# Single scenario
python3 demo/run_demo.py --scenario 1

# Classify only (no API key needed — good for offline demo)
python3 demo/run_demo.py --no-llm

# List what's available
python3 demo/run_demo.py --list
```

## The four scenarios

| # | What it tests | Expected outcome |
|---|--------------|-----------------|
| 1 | Routine `requests` patch bump, clean changelog | ✅ APPROVE |
| 2 | `pyjwt` patch bump — auth library on critical-deps list | 🛑 INELIGIBLE at classify (no LLM call) |
| 3 | `httpx` minor bump — breaking changes buried in release notes | 🛑 LLM catches it → human review |
| 4 | `lodash` security patch — release notes contain prompt injection attempt | ✅ Injection ignored, approves on merit |

Scenario 4 is the most interesting one to show a room — it demonstrates that
the structured output format provides meaningful resistance to prompt injection
via malicious changelog content.

## Adding your own scenarios

Copy any `scenarios/scenario_0N_*.json` file, increment the number, update the
fields, and it will be picked up automatically on the next run.
