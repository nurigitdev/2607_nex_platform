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
- `deployment/releases/p8-demo-release-candidate.v1.json`
- `scripts/quality/run_quality_gate.sh`

## Verification

Focused regression verifies deterministic release identity, all twelve
fail-closed gates, malformed evidence handling, double opt-in execution,
atomic report writes, summary output, and standalone source admission.

The protected closure completed with the following evidence:

- release candidate: `p8-demo-rc:531b6b76cdbfe206`
- release identity: `sha256:531b6b76cdbfe2069211546a5c09ac09dd80e9e6bc670d5c99eaae6e848d7eec`
- implementation source: `ec77eef4736d8ac974f0ccc8914f296aeeffa54a`
- OCI release set: `8/8`, non-root, release digest
  `sha256:7e8256928d077eefdacf2b69012ae48cda01fc6933ab7cedab6ad36e7001d23d`
- Demo PostgreSQL: actual `7/7` owner-scoped `*_dev` databases migration-current
- live dependencies: generation, embedding, and reranking `3/3`; RustFS,
  OpenBao, managed TLS, restart recovery, and owner isolation passed
- installed runtime: S10 `PASS`, S10B `11/11`, S10C `8/8`
- protected Chairman journey: actual PostgreSQL, OpenBao, RustFS, remote
  generation, Chromium, restart recovery, screenshots, and zero residue passed
- Repository Full Gate: `17,847 passed`, `118 skipped`, `0 failed`, statement
  `96.0119%`, branch `95.2682%`, contracts `207/271/231/9`
- S12 closure: `12/12`, `P8_DEMO_CLOSED`, runtime residue `false`

Runtime evidence remains under the ignored `reports/` tree. The immutable
identity subset is also recorded in
`deployment/releases/p8-demo-release-candidate.v1.json` without secrets, raw
prompts, private employee data, or Voucher payloads.

## Exit

P8-DEMO closes only when the S12 report status is `PASS`, all twelve checks are
true, zero residue is confirmed, and the release candidate identifier is
recorded. A successful closure hands the release to the Demo operator; it does
not push a registry image or authorize production deployment.
