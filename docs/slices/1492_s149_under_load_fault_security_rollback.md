# Slice 1492: S149 Under-load Fault, Security, and Rollback Acceptance

Status: Complete. Protected execution requires explicit opt-in and writes an
ignored metadata-only report.

## Outcome

- Added a protected three-minute shadow workload bound to the exact passing
  Slice 1491 release candidate and immutable six-image release-set digest.
- Scheduled exactly `1,440` actual PostgreSQL/provider boundary operations at
  `8 RPS`: 480 readiness, 288 OA trust, 288 AG operations, 144 CX persistence,
  144 AE artifact, 90 hybrid retrieval, and 6 grounded generation probes.
- Exercised all eight allowlisted S149 client-route fault scenarios while the
  shadow workload was active. Every injected failure must be followed by a
  successful actual recovery probe and zero rehearsal residue.
- Re-ran deterministic fault, security/privacy, and rollback contracts during
  the active load interval.
- Re-ran actual S144 trust/federation, S146 RustFS restart/isolation, and S147
  provider readiness/rollout acceptance during the same interval.
- Admitted the immutable Slice 1491 OCI release set through a pinned image
  loader. The loader requires the exact predecessor release digest and allows
  only post-build changes under `docs/`, `tests/`, and `scripts/smoke/`;
  runtime-affecting or dirty tracked changes fail closed.
- Forced generation health probes to `reasoning_mode=disabled` and required
  both the shadow workload and S147 provider evidence to report that mode.
- Preserved the Slice 1491 release digest and prohibited production contact,
  production approval, and DGX provider-process mutation.
- Kept exported evidence metadata-only. Credentials, endpoint and database
  URLs, private payloads, physical paths, and per-request records are omitted.

## Decision

Single-host fault injection remains at the client or staging-route boundary.
The acceptance runner verifies actual service, trust, storage, database, and
provider recovery but does not stop or reconfigure DGX processes. Node loss,
replica promotion, distributed object-store quorum, and GPU failover remain
explicit post-S150 backlog and cannot be claimed by this Slice.

## Protected Execution

Execution requires the passing Slice 1491 report, all five test-database
bindings, the three remote-provider bindings, Docker/RustFS acceptance
dependencies, and explicit opt-in:

```bash
NEX_S149_UNDER_LOAD_ACCEPTANCE=1 \
  ./.venv/bin/python \
  scripts/smoke/run_s149_under_load_fault_security_rollback.py \
  --execute --summary
```

The report is written to
`reports/deployment/s149-under-load-acceptance.json`. Sixteen fail-closed
checks cover release binding, exact load/mix, provider-operation success,
active-load overlap, fault recovery, security/privacy, rollback, RustFS
restart/isolation, provider readiness, digest preservation, cleanup, and
non-mutation boundaries. Pinned-release admission and disabled generation
reasoning are additional mandatory checks.

## Verification

- Unit tests cover opt-in/profile guards, exact shadow planning, all admission
  checks, fault state transitions, recovery failure, predecessor validation,
  redaction, source adapters, report output, and CLI behavior.
- The protected run fails when any required source finishes after the load,
  any retrieval or generation probe fails, fewer than eight faults recover,
  release identity drifts, a source fails, or cleanup leaves residue.
- Slice 1493 owns evidence aggregation, topology limitation classification,
  and S150 admission. Slice 1494 owns the runbook and Full Gate.
