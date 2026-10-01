# Slice 1213: OA subject lifecycle domain

## Goal

Define subject status transitions as a deterministic, persistence-independent
domain contract before adding storage or HTTP behavior.

## Behavior

- `ACTIVE` may become `DISABLED` or `DELETED`.
- `DISABLED` may become `ACTIVE` or `DELETED`.
- `DELETED` is terminal.
- The caller supplies the current expected revision. Stale writes fail with a
  revision conflict.
- A real status change requires a bounded machine-readable reason code and
  advances revision exactly once.
- A same-status request is idempotent and does not advance revision.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_identity_lifecycle.py \
  --test tests/test_oa_subject_lifecycle_domain.py \
  --coverage-target services/nex-oa/nex_oa/identity_lifecycle.py \
  --coverage-target scripts/smoke/run_oa_subject_lifecycle_domain.py \
  --smoke scripts/smoke/run_oa_subject_lifecycle_domain.py
```
