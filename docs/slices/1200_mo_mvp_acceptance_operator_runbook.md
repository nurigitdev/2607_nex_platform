# Slice 1200: MO MVP acceptance privacy and operator runbooks

## Goal

Turn MO MVP acceptance failures into executable, privacy-safe operating
procedures before final acceptance and OA transition are allowed.

## Runbooks

The evidence runner verifies seven bounded procedures:

1. PostgreSQL connectivity or migration failure
2. Provider outage or model drift
3. Runtime precision, process, SSH, or GPU evidence failure
4. Regression or coverage failure
5. Privacy or secret exposure
6. Protected-smoke cleanup residue
7. OA handoff tamper or hash mismatch

Every procedure defines detection, containment, recovery, verification, and
the `nex-mo-operations` owner. Recovery always requires fresh evidence; a stale
or partly successful result cannot be reused.

## Operator Flow

1. Read the blocked gate and bounded reason code from the protected acceptance
   projection. Do not collect raw provider or infrastructure payloads into the
   incident record.
2. Contain the affected boundary: disable acceptance publication, isolate only
   probe-owned rows, or deny handoff consumption as directed by the runbook.
3. Repair the source condition. Never bypass model identity, BF16, database
   identity, cleanup, privacy, or hash verification.
4. Rerun the narrow protected smoke, then the applicable Slice/Checkpoint/Full
   Gate. Only a fresh `PASS` can clear the blocker.
5. For privacy exposure, stop publication first and rotate potentially exposed
   material before regenerating evidence.

## Failure Matrix

The runner starts from nine passing S120 gates and proves that twelve isolated
mutations each block exactly one gate. It covers missing/stale evidence,
regression, branch coverage, database identity, cleanup, model drift,
capability availability, provider failure, BF16 mismatch, runbook inventory,
and handoff sealing.

## Privacy

The evidence recursively rejects authorization, credential, database URL,
endpoint, password, provider payload, secret, and SSH target keys. It retains
only statuses, bounded failure codes, counts, relative repository paths, and
handoff state.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_mvp_acceptance_privacy_runbook_evidence.py \
  --cov=run_mo_mvp_acceptance_privacy_runbook_evidence \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_mvp_acceptance_privacy_runbook_evidence.py --summary
```

No table or migration is added. Next Slice: `1201`.

## Result

- Slice Gate: `1052 passed, 6 skipped`; statement coverage `99.88%`, branch
  coverage `99.56%`.
- Runbook evidence: checks `7/7`, runbooks `7`, isolated failure cases `12`.
- Runner scope: statement and branch coverage `100%/100%`.
- Full Gate hook is registered for continuous runbook and privacy verification.
