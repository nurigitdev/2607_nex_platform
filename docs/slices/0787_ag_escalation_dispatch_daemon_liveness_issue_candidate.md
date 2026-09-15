# Slice 0787: AG dispatch daemon liveness issue-candidate integration

## Objective

Promote enabled AG operator review escalation dispatch daemon liveness failures
into the unified AG operations issue-candidate surface.

## Scope

- Added issue rule
  `operator_review_dispatch_daemon_liveness_attention_required.v1`.
- Added candidate generation for enabled daemon `STALE` and `MISSING`
  heartbeat states.
- Guarded disabled daemon process state so missing heartbeat does not create a
  false positive when the daemon is intentionally disabled.
- Reused the dashboard `daemon_liveness` subsection from Slice 0786.
- Kept source `UNAVAILABLE` handling on the existing degraded-source rule path.
- Changed liveness projection default `checked_at` to current UTC time while
  still honoring explicit `checked_at` for deterministic tests.
- Introduced no new table and no write mutation.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dispatch_daemon_liveness or issue_candidate_projection_includes_dispatch_daemon or issue_candidate_rules"
```

Result: `7 passed, 191 deselected, 1 warning in 0.87s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `198 passed, 1 warning in 11.12s`.

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q
```

Result: `28 passed in 2.74s`.

Coverage for `nex_ag.operations`: statement/branch remained in the existing
high-coverage band.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5212 passed, 1 warning in 316.09s`.

Coverage totals: statement `98.69%` (`66755/67640` lines covered),
branch `96.07%` (`15928/16580` branches covered).
