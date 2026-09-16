# Slice 0806: AG dispatch liveness acknowledgement/suppression dashboard and issue overlay

## Objective

Surface persisted dispatch daemon liveness acknowledgement/suppression state in
the recovery plan, operations dashboard, and issue-candidate projections without
mutating or suppressing the source liveness projection.

## Scope

- Added `acknowledgement_state_overlay` to the dispatch daemon liveness recovery
  plan.
- Wired the same overlay into the operations dashboard
  `operator_review_escalation_dispatches.daemon_recovery` section.
- Added the safe overlay summary to dispatch daemon liveness issue-candidate
  signals.
- Wired the protected recovery-plan, dashboard, and issue-candidate routes to
  the AG liveness acknowledgement state store.
- Extended the AG operations projection JSON schema and dashboard mock example
  for the new overlay.
- Added regression coverage for state-present, no-state, store-unavailable,
  dashboard, issue-candidate, and protected route wiring paths.

## Decisions

- The overlay is read-only. It reports persisted acknowledgement/suppression
  state but never hides or mutates `service_worker_heartbeats`.
- Issue candidates remain visible even when an acknowledgement or suppression
  state exists; operators see the overlay instead of losing the signal.
- Dedicated PostgreSQL smoke evidence remains Slice 0808.
- OpenAPI hardening remains Slice 0807; this slice includes the JSON schema
  extension required by the existing regression contract checks.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack_api.py -q --tb=short
```

Result: `21 passed, 1 warning in 2.66s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q --tb=short
```

Result: `208 passed, 1 warning in 7.01s`.

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q --tb=short
```

Result: `28 passed in 4.73s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_ag_operator_review_liveness_ack.py tests/test_nex_ag_operator_review_liveness_ack_api.py tests/test_contract_validation.py -q --tb=short
```

Result: `274 passed, 1 warning in 9.16s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5322 passed, 1 warning in 329.10s`.

Coverage totals from `/tmp/nex_platform_0806_coverage.json`:

- Statement coverage: `68303 / 69186 = 98.7237302344405%`.
- Branch coverage: `16269 / 16920 = 96.15248226950355%`.
