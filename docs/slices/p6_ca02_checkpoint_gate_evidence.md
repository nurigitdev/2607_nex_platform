# P6-CA02 S1-S5 Checkpoint Gate Evidence

**Status:** PASS
**Date:** 2026-10-16
**Revision:** `d6bfa4b1dd074dbf564796618e80b3603458541c`
**Branch:** `transition/p4-agent-runtime-foundation`
**Host:** `tprover-X110`
**Python:** `3.12.13`

## Purpose

This evidence records the fifth-Slice Checkpoint Gate after P6-CA02-S1 through
P6-CA02-S5. It verifies that dependency admission, dual-profile persistence,
the in-process READ adapter, exact profile routing, and default worker
readiness compose without repository-wide regression.

The Checkpoint Gate remains narrower than the Full Gate: requirement closure
tests are excluded by policy, while all non-closure tests under `tests/` and
all `services` and `providers` coverage are included. The canonical Full Gate
remains mandatory at P6-CA02 closure or immediately before P7 entry.

## Execution

The gate was run through the canonical wrapper with four explicitly enabled
protected smoke scripts:

```text
scripts/quality/run_checkpoint_gate.sh
  --smoke scripts/smoke/run_p6_ca02_s2_postgres_smoke.py
  --smoke scripts/smoke/run_p6_ca02_s3_in_process_smoke.py
  --smoke scripts/smoke/run_p6_ca02_s4_profile_routing_smoke.py
  --smoke scripts/smoke/run_p6_ca02_s5_worker_readiness_smoke.py

database target: nex_ae_user@127.0.0.1/nex_ae_test
NSL source target: /home/tprover/2608_nsl
secret values: omitted
result: PASS
commands: 7/7
duration: 748.914 seconds
```

## Regression and Coverage

```text
passed: 13,965
skipped: 33 protected tests
failed: 0
errors: 0
warnings: 897
pytest duration: 730.28 seconds

statements: 83,339
covered statements: 82,500
statement coverage: 98.99% (threshold 95.00%)
branches: 25,040
covered branches: 24,440
branch coverage: 97.60% (threshold 94.00%)

contract validation: PASS
schemas: 174
examples: 236
negative examples: 204
OpenAPI documents: 7
```

The 33 skipped tests are unrelated protected PostgreSQL, DGX, browser,
deployment, and production profiles. They are expected in the Checkpoint
policy and do not include the four P6-CA02 protected checks listed below.

## Protected P6-CA02 Evidence

```text
P6-CA02-S2 dual-profile PostgreSQL smoke:
  status: PASS
  actual PostgreSQL: true
  checks: 9/9
  migrations: 44 current
  latest migration: 2205_ae_nsl_dual_profile
  in-process and process-isolated round trips: PASS
  cleanup: zero residue for both profiles

P6-CA02-S3 in-process READ smoke:
  status: PASS
  actual installed wheel: true
  checks: 10/10
  profile: NSL_V01_IN_PROCESS

P6-CA02-S4 exact-profile routing PostgreSQL smoke:
  status: PASS
  actual PostgreSQL: true
  checks: 5/5
  latest migration: 2205_ae_nsl_dual_profile
  in-process and process-isolated routes: PASS
  cleanup: zero residue for both profiles

P6-CA02-S5 worker readiness smoke:
  status: PASS
  actual installed wheel: true
  checks: 8/8
  default profile: NSL_V01_IN_PROCESS
```

No remote embedding, reranking, or generation provider was required. This
checkpoint validates AE Runtime and NSL package/database boundaries only.

## Evidence Integrity

Raw reports remain local under ignored `reports/` paths. Their hashes at the
time of this bounded evidence record are:

```text
f963514b686f1ce8a8e95c07fd987a37e9cfa44a7d0cb6d656ccb2b98a8e7165  reports/quality/checkpoint.coverage.json
f774154b0b6b20a6d6ed46282f1b7632a00e53f2044ccefea65c6eb69d9c1c6b  reports/quality/checkpoint-latest.json
3be02f68e256d0b19b2add96940cc03d4421151f9473209460c489139e5ed432  reports/smoke/p6-ca02-s5-worker-readiness.json
```

## Decision

P6-CA02-S1 through P6-CA02-S5 pass the fifth-Slice Checkpoint Gate. The
in-process default is accepted for continued implementation, historical
process-isolated compatibility remains supported, and no corrective source or
schema change is required. The Full Gate is deferred only to the canonical
P6-CA02 closure or P7-entry boundary.
