# P8-S05: NSL v0.2 Public API Adapter Foundation

## Status

Completed on 2026-10-21. AE now has one narrow, fail-closed integration
boundary for the NSL v0.2 public API admitted by P8-S01 through P8-S04.

## Goal

Expose only the NSL v0.2 symbols required by P8 while preventing an AE
runtime from importing an unadmitted package, stale API surface, or private
NSL implementation module.

## Source Audit and Changes

- Added `nex_ae_api.nsl_v02_public_api` as the sole P8 v0.2 public API adapter.
- Required exact `nsl_installed_package_readiness.v2` evidence, package version
  `0.2.0`, v2 wheel lock, installed-distribution origin, passing readiness,
  and a valid release admission hash before importing NSL.
- Restricted the admitted surface to these ten `nsl.api` symbols:

```text
ApprovalRequest
ApprovalEvidence
ApprovalSuspensionCoordinator
ApprovalResumeCoordinator
CheckpointPort
ResumeCheckpointPort
IdempotencyCoordinator
WriteExecutionPort
PostWriteVerificationPort
RuntimePreflightValidator
```

- Verified the imported symbol names against the admitted ordered inventory.
- Bound the resulting adapter to a semantic API contract hash containing its
  schema, package version, release admission hash, and exact symbol inventory.
- Kept the import lazy so the Platform host can preserve its installed NSL
  v0.1 compatibility environment until an admitted v0.2 worker is composed.
- Added an AST architecture test that rejects any NSL import other than the
  exact `nsl.api` import. No `nsl.internal` or other private dependency exists.

## Runtime Boundary

This Slice does not activate a v0.2 execution backend, mutate EOS, or replace
the v0.1 default profile. It establishes the admitted adapter needed by the
isolated compatibility smoke in P8-S06.

## Verification

- Focused P8-S03 through P8-S05 regression: `30 passed` before the final test
  hardening.
- Adapter unit and architecture tests: `14 passed`; statement `100%`, branch
  `100%`.
- Fifth-Slice Checkpoint Gate: `14,820 passed`, `47` protected infrastructure
  tests skipped; statement `98.69%`, branch `97.15%`.
- Adapter scope within the Checkpoint Gate: statement `100%`, branch `100%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  8 OpenAPI documents.
- Ruff and `git diff --check`: passed.
- Platform Full Gate: deferred until P8-S06 as required.

## Exit Decision

P8-S05 is closed. P8-S06 may now prove v0.1 READ regression, v0.2 READ,
v0.2 controlled-prefix WRITE behavior, and zero EOS mutation before the final
Full Gate closes P8.1.
