# Slice 0982: CX Asynchronous Grounded Generation Recovery Boundary Audit

## Goal

Freeze the S99 boundary before adding asynchronous grounded-generation code.

## Decision

- Keep the existing synchronous generation route compatible.
- Reuse `service_jobs`, S98 atomic claims, leases, bounded workers, cooperative
  cancellation, retry/dead-letter policy, heartbeat, and reconciliation.
- Persist the complete generation request as an immutable owner-private
  envelope; queue rows carry metadata and integrity references only.
- Use deterministic generation and job identities so an interrupted admission
  can be retried safely.
- Add no table unless later evidence proves the existing admission, execution,
  and job tables insufficient.
- Run deterministic mock-provider tests while remote providers are unavailable.
- Require actual `nex_cx_test` evidence in Slice 0990; defer only remote-provider
  live smoke.

## Slice Plan

Slices 0983 through 0990 close the eight audited gaps. Slice 0986 is the
Checkpoint Gate and Slice 0991 is the Full Gate and S99 closure.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_cx_async_generation_recovery_boundary_audit.py \
  --cov=run_cx_async_generation_recovery_boundary_audit \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_async_generation_recovery_boundary_audit.py \
  --summary
```
