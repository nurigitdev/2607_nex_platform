# Slice 0881: AG audit retention, archive, and purge boundary audit

## Goal

Start S89 by fixing the ownership and safety boundary for retention, archive,
and physical purge of AG audit events and redacted evidence exports.

## Findings

- `service_operational_events` and `ag_ev_exports` remain the two source tables.
- The evidence-export store has an immediate row delete method, but there is no
  operator-facing archive receipt, purge tombstone, or retention policy.
- The operational-event store has no retention-candidate or guarded purge
  contract.
- Service-log retention provides reusable dry-run and execution conventions,
  but it is a separate dataset and cannot act as the S89 source of record.
- A source row is not an archive. Keeping its hash after deletion proves
  identity but cannot restore its payload.

## Recommended Boundary

- NeX-AG owns retention policy, candidate selection, archive receipt state,
  purge admission, lifecycle evidence, and operations projection.
- An injected external archive adapter owns recoverable payload storage. Object
  storage vendor selection remains deferred.
- NeX-AG persists only a sealed archive receipt and purge tombstone in the
  proposed `ag_ret_archives` table. The name is 15 characters and remains under
  the project 30-character identifier limit.
- Metadata-only manifests must not authorize physical purge. Purge requires a
  sealed receipt from the archive adapter, an elapsed grace period, explicit
  execute confirmation, and a second eligibility check in the same unit of
  work as deletion.
- Dry-run is the default. Existing direct store delete methods remain internal
  cleanup primitives and must not become operator-facing commands.

This storage decision requires confirmation before Slice 0882 freezes policy
and before Slice 0884 introduces the receipt table.

## Proposed Slice Plan

- Slice 0881: boundary audit and storage decision checkpoint.
- Slice 0882: validated retention/archive policy contract.
- Slice 0883: bounded retention-candidate read model.
- Slice 0884: archive receipt persistence and sealing.
- Slice 0885: guarded idempotent physical purge execution.
- Slice 0886: lifecycle operations projection.
- Slice 0887: OpenAPI, JSON Schema, and index hardening.
- Slice 0888: actual `nex_ag_test` archive/purge PostgreSQL smoke.
- Slice 0889: privacy, failure-mode, and operator runbook evidence.
- Slice 0890: S89 closure checkpoint.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_audit_retention_archive_purge_boundary_audit.py \
  --summary

./.venv/bin/pytest -q \
  tests/test_ag_audit_retention_archive_purge_boundary_audit.py \
  --cov=run_ag_audit_retention_archive_purge_boundary_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
boundary audit: PASS, decision=CONFIRMATION_REQUIRED
focused tests: 6 passed
boundary runner statement/branch: 100%
aggregate regression: 6017 passed, 1 known warning
statement=73727/74608=98.819161484023%
branch=17234/17884=96.365466338627%
```
