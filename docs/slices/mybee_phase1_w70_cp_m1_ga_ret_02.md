# CP-M1-GA-RET-02: Golden A Active Binding Removal and Historical Quarantine

## Status

- State: CLOSED
- Date: 2026-11-16
- Database migration: none
- Remote provider: not required
- Canonical runtime: `VERIFIED_PRODUCT_RELEASE`

## Scope

This Slice removes Golden A from the active MyBee M1 selection, runtime,
prompt, image, Compose, and rollback boundaries after the generalized D04/D12
runtime passed `CP-M1-E2E-FX-01A.1` through `.5`. Historical source, registry,
bundle, evidence, migration, and replay assets remain immutable and are pinned
by a quarantine manifest.

## Implemented Boundary

1. Published `ae-product-capability-registry.mybee-m1.v2.json` with only
   `FINANCE.VOUCHER.APPROVE_AND_POST` and `PROJECT.WORK_CODE_SET.GET`.
2. Published matching runtime admission v2, generalized activation v2, and a
   generalized M1 rollback receipt. The rollback target no longer contains a
   Golden A profile or dependency.
3. Removed the Golden A rollback profile from the installed runtime factory.
   Unsupported legacy profile selection now fails closed.
4. Removed the fixed Golden A consumer from the installed AE worker and the
   Golden activator builder from semantic admission.
5. Promoted the active intent prompt to scenario-free v9. Prompt v8 and older
   scenario prompts remain replay-only history.
6. Removed Golden authority, Skill root, bundle manifest, retirement
   projection, and rollback receipt from canonical Compose/OCI inputs.
7. Changed canonical image staging to package the admitted NSL wheel and
   generalized M1 release assets only.
8. Added an immutable historical quarantine manifest, deterministic artifact
   builder, zero-active-residue Gate, and protected PostgreSQL smoke runner.
9. Replaced the RET-01 active deployment Gate in Repository Full Gate with the
   RET-02 quarantine Gate while preserving RET-01 historical contract tests.

## Historical Quarantine

- Manifest:
  `deployment/retirement/golden-a-historical-quarantine.v1.json`
- Policy: new selection denied, active imports denied, canonical image
  packaging denied, offline replay only, destructive database cleanup denied.
- Deprecated EOS voucher-draft API aliases remain available for compatibility;
  their physical removal requires a separate caller-inventory decision.

## Verification

- Deterministic successor artifact check: PASS
- Active import/config/prompt/image residue Gate: PASS
- Focused unit and regression tests: PASS
- Actual `nex_ae_test` PostgreSQL read-only lineage smoke: PASS
- Slice Gate with statement and branch coverage: PASS
- Secret included: no
- Database mutation performed by smoke: no

Evidence:

- `reports/quality/mybee-w70-ga-ret-02-gate.json`
- `reports/smoke/mybee-w70-ga-ret-02-postgres.json`

## Result

Golden A is no longer an active product dependency. Its reusable runtime
mechanisms remain covered by generic D04/D12 and Agent Runtime regression, and
its scenario-specific assets are retained only as hash-pinned historical
evidence. The next boundary may return to `CP-M1-E2E-FX-01` without a Golden A
runtime rollback obligation.
