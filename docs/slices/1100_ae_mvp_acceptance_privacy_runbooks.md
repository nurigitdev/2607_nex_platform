# Slice 1100: AE MVP Acceptance Privacy and Failure Runbooks

## Goal

Turn the AE MVP acceptance failure boundaries into an executable, privacy-safe
operator runbook inventory before final acceptance is allowed.

## Runbooks

The evidence runner verifies seven bounded procedures:

1. PostgreSQL connectivity or migration failure
2. Provider outage or model drift
3. Browser lifecycle or verified-response failure
4. Regression or coverage failure
5. Privacy or secret exposure
6. Protected-smoke cleanup residue
7. Operations handoff tamper or hash mismatch

Every procedure identifies detection, containment, recovery, verification, and
the `nex-ae-operations` owner. Recovery always requires fresh evidence; stale or
partially successful results cannot be reused.

## Failure Matrix

The runner starts from all nine passing S110 gates and proves that eleven
independent mutations each block exactly one expected gate. The matrix covers
missing/stale evidence, regression, branch coverage, database identity,
cleanup, model drift, provider calls, browser presentation, runbook inventory,
and handoff sealing.

## Privacy

The evidence projection recursively rejects credential, database URL, private
content, raw payload, and secret-bearing keys. It contains only statuses,
bounded reason codes, counts, relative repository paths, and handoff state.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_ae_mvp_acceptance_privacy_runbook_evidence.py \
  --cov=run_ae_mvp_acceptance_privacy_runbook_evidence \
  --cov-branch --cov-report=term-missing

./scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_mvp_acceptance_privacy_runbook_evidence.py \
  --coverage-target scripts/smoke/run_ae_mvp_acceptance_privacy_runbook_evidence.py \
  --smoke scripts/smoke/run_ae_mvp_acceptance_privacy_runbook_evidence.py
```
