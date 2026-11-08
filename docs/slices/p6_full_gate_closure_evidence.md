# P6 Full Gate Closure Evidence

**Status:** PASS
**Date:** 2026-10-15
**Revision:** `284a6d766b337d5f4d21c3b6e0f9edbfa1124a88`
**Branch:** `transition/p4-agent-runtime-foundation`
**Host:** `tprover-X110`
**Python:** `3.12.13`

## Purpose

This evidence closes the P6 quality-process gap left by the intentionally
omitted fifth-Slice Checkpoint Gate. It records one repository-wide Full Gate
after P6-S7 and supplements the protected default run with the actual P6 IA
READ PostgreSQL/NSL acceptance.

## Full Gate Execution

```text
command: ./scripts/quality/run_quality_gate.sh
started: 2026-10-15T09:36:55+09:00
completed: 2026-10-15T10:18:29+09:00
exit code: 0
result: PASS
```

The gate ran the repository-wide pytest suite, coverage thresholds, contract
validation and the complete post-pytest smoke chain defined by
`scripts/quality/run_quality_gate.sh`.

```text
collected: 14626
passed: 14592
skipped: 34
failed: 0
errors: 0
warnings: 1131
pytest duration: 1736.37s (00:28:56)

statements: 154947
covered statements: 150714
statement coverage: 97.27% (threshold 95.00%)
branches: 34400
covered branches: 33277
branch coverage: 96.74% (threshold 85.00%)

contract validation: PASS
schemas: 174
examples: 236
negative examples: 204
OpenAPI documents: 7
```

All P4, P5 and P6 test modules were collected by the repository-wide pytest
run. The only skipped P6 pytest case was the explicitly protected P6-S7 live
PostgreSQL case, which was executed separately below with its guard enabled.

The other pytest skips and post-pytest smoke skips are protected PostgreSQL,
DGX, browser, deployment or production-acceptance profiles that require an
explicit environment opt-in. They did not fail the canonical Full Gate. They
do not weaken the P6 decision because P6 does not require remote model
providers and its actual database/NSL journey was repeated directly.

## Protected P6 Acceptance

The P6-S7 smoke was repeated after the Full Gate against the actual test
database and the source-backed NSL v0.1 checkout.

```text
status: PASS
actual PostgreSQL: true
database/role: nex_ae_test / nex_ae_user
migrations: 43 current
latest migration: 2204_ae_nsl_backend_run
NSL revision: 803f22aadc3946a48b05472c80b60fe11d9d9554
checks: 23/23
RuntimeJobs/attempts: 2/2
StepResults: 2
NSL executions: 1
AgentResults/ResultDeliveries: 1/1
ResultDelivery state: PENDING
timeline events/gaps: 29/3
remaining P6-S7 rows after cleanup: 0
remote model providers: not required
```

The smoke confirms actual database identity, migration currency,
capability-aware dispatch, worker restart deduplication, exact source-backed
READ execution, deterministic lineage and hashing, dependent step completion,
atomic result finalization, restart-stable timeline projection, private-prompt
absence and zero residue.

## Evidence Integrity

Raw reports remain local under ignored `reports/` paths; this bounded document
is the version-controlled evidence record.

```text
a28fab8dae401159294e85c5513f1c1d7cec10948fd17a1a49642c39b9b0d0c1  reports/quality/p6-full-gate-20261015.log
abade0bdd0f5e55c356651d5b01c5b58e0433b78e12a896b953a886410e41627  reports/coverage/coverage.json
5b3e7064749363f48238171b471e1a8c8d1b2078d106190d369f061d73f74aee  reports/coverage/junit.xml
43765c57ac497667c2ea16fe1a38f254f0c214af8b067f87cb6c54f34c618796  reports/quality/p6-s7-postgres-nsl-smoke-20261015.json
```

## Decision

P6 is accepted as complete. The missing Checkpoint Gate is explicitly waived;
the repository-wide Full Gate passed, and the protected P6 PostgreSQL/NSL
acceptance passed independently with zero residue.
