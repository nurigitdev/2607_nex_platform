# Slice 0894: AG MVP acceptance evaluator

## Goal

Turn S90 policy and evidence into one deterministic, fail-closed AG service MVP
acceptance and CX transition decision.

## Evaluation Rules

- All eight blocking gates must pass; one blocker produces `BLOCKED`.
- Every evidence item requires its own timezone-aware `observed_at` value and is
  checked against the policy freshness window. Evidence more than five minutes
  in the future is also blocked.
- `SKIPPED`, missing, malformed, stale, and unknown gate evidence is never
  silently accepted.
- Closure counts, contract family counts, regression totals, both coverage
  values, PostgreSQL backend/database/cleanup, runbook count, and sealed CX
  handoff identity receive gate-specific validation.
- The evaluator emits only normalized gate states and reason codes. It does not
  echo raw test logs, DB URLs, credentials, environment values, or evidence
  payloads.
- A SHA-256 acceptance ID is deterministic for the same policy, evaluation
  time, and normalized gate statuses.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_mvp_acceptance_evaluation.py \
  --cov=nex_ag.mvp_acceptance_evaluation \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
focused evaluator tests: 26 passed
evaluator statement/branch coverage: 100%
aggregate regression: 6209 passed, 1 known warning
statement=75064/75945=98.839949963790%
branch=17562/18212=96.430924665056%
```
