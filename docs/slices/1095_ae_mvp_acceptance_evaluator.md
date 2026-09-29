# Slice 1095: AE MVP Acceptance Evaluator

## Goal

Convert the AE acceptance policy and fresh server-derived evidence into one
deterministic, privacy-safe, fail-closed service MVP decision.

## Evaluation Rules

- All nine blocking gates must pass; one blocker returns `BLOCKED`.
- Every item has a timezone-aware `observed_at`, is no older than the policy
  window, and is no more than five minutes in the future.
- Missing, malformed, stale, future-dated, and `SKIPPED` evidence blocks.
- Coverage, regression, both PostgreSQL databases, zero residue, exact live
  models, Chromium, `VERIFIED_RESPONSE`, runbooks, and sealed NeX-AG operations
  handoff receive gate-specific validation.
- The report includes normalized gate states and reason codes only. Raw test
  logs, prompts, responses, source content, endpoints, credentials, database
  URLs, and storage paths are excluded.
- The acceptance ID is a deterministic SHA-256 of policy, evaluation time, and
  normalized gate statuses.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ae_mvp_acceptance_evaluation.py \
  --cov=nex_ae_api.mvp_acceptance_evaluation \
  --cov-branch --cov-report=term-missing
```

Passing evidence returns `ACCEPTED` and `READY_FOR_OPERATIONS`. No table or
migration is added.
