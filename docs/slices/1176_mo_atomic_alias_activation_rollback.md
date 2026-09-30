# Slice 1176: MO atomic alias activation and rollback

## Goal

Switch and roll back logical provider aliases atomically with optimistic
revision guards and complete binding history.

## Result

- Added atomic validation, prior-binding state update, and replacement insert in
  one repository transaction.
- Added first activation, candidate promotion, stale-writer rejection, and
  single-active-binding enforcement.
- Added rollback to the immediate prior catalog target as a new revision while
  marking the replaced candidate binding `ROLLED_BACK`.
- Rejected inactive targets, capability mismatch, invalid lineage, missing
  history, and retired rollback targets.
- Ran the fifth-Slice Checkpoint Gate after focused alias lifecycle regression.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_alias_lifecycle.py
./.venv/bin/python scripts/smoke/run_mo_alias_lifecycle.py --summary
scripts/quality/run_checkpoint_gate.sh --service nex-mo
```
