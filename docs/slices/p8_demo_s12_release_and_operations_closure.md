# P8-DEMO-S12: Demo Release and Operations Closure

## Purpose

P8-DEMO-S12 closes the dedicated Chairman Demo branch as an operable,
reproducible single-host release candidate. It introduces no business API,
database migration, approval rule, NSL Skill behavior, or alternative runtime
implementation.

## Closure Contract

The new fail-closed closure runner admits only a complete evidence graph:

```text
clean one-revision eight-image release set
+ enriched non-root AE image with admitted NSL v0.2.1 bundle
+ rendered P8 Compose topology bound to that image set
+ seven migration-current *_dev PostgreSQL databases
+ live OpenBao trust and TLS admission
+ live generation/embedding/reranking and RustFS admission
+ installed S10/S10B/S10C runtime acceptance
+ S11 authenticated Chairman browser journey and restart recovery
+ fresh Repository Full Gate at 96% statement / 94% branch
= immutable p8-demo-rc:<digest>
```

Every protected source must be an executed `PASS`. `SOURCE_ADMITTED`, mock
fallback, stale coverage, mismatched image digest, nonzero restart queue,
secret-bearing report, or missing runbook blocks closure.

## Operations Boundary

`docs/runbooks/p8_chairman_demo_release.md` records the exact preparation,
backup, migration, build, trust, dependency, installed acceptance, browser
journey, start/stop/restart, triage, cleanup, and closure order. Database reset
remains tenant-scoped, registry push is not performed, and production
deployment is not implied.

## Source Changes

- `scripts/deployment/run_p8_demo_s12_release_operations_closure.py`
- `tests/test_nex_platform_p8_demo_s12_release_operations_closure.py`
- `docs/runbooks/p8_chairman_demo_release.md`
- `scripts/quality/run_quality_gate.sh`

## Verification

Focused regression verifies deterministic release identity, all twelve
fail-closed gates, malformed evidence handling, double opt-in execution,
atomic report writes, summary output, and standalone source admission.

Final protected values are recorded after the current source images, S11
journey, and Repository Full Gate are rerun. Runtime evidence remains under
the ignored `reports/` tree; the final release identifier and gate totals are
recorded here without secrets, raw prompts, private employee data, or Voucher
payloads.

## Exit

P8-DEMO closes only when the S12 report status is `PASS`, all twelve checks are
true, zero residue is confirmed, and the release candidate identifier is
recorded. A successful closure hands the release to the Demo operator; it does
not push a registry image or authorize production deployment.
