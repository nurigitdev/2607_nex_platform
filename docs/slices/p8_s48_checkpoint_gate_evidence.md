# P8-S44-S48 Checkpoint Gate Evidence

**Status:** PASS

**Date:** 2026-10-22

**Base revision before reconciliation:**
`3c79547d17597b2478d545f52be53e60ebf01aa9`

**Branch:** `transition/p4-agent-runtime-foundation`

**Python:** `3.12.13`

## Purpose

This evidence closes the requested Checkpoint Gate after P8-S48. The covered
P8.4 implementation persists protected NSL ApprovalRequest bytes in AE
PostgreSQL, generalizes and exactly binds AE waits, publishes idempotent WC
ApprovalWorkItems, and persists AE-owned immutable Platform ApprovalEvidence.

## Baseline Reconciliation

The first repository Checkpoint run stopped with two assertions from one
production-readiness audit:

```text
platform_runtime_deployment_coupling_audit
loopback_baseline_exact: FAIL
observed: 48 occurrences / 28 files
frozen expectation: 47 occurrences / 27 files
```

The additional occurrence and file are the approved S47 AE-to-WC HTTP client
default in `nsl_approval_publication.py`. It is service-local development
topology, remains forbidden in production, and does not introduce a direct
database or provider coupling. The frozen inventory was therefore reconciled
to `48/28`; no threshold or production policy was weakened.

Focused reconciliation verification:

```text
tests/test_platform_runtime_deployment_coupling_audit.py
5 passed
```

## Final Execution

The canonical repository Checkpoint wrapper was rerun after reconciliation:

```text
scripts/quality/run_checkpoint_gate.sh

result: PASS
commands: 3/3
duration: 876.461 seconds
```

## Regression And Coverage

```text
passed: 15,524
skipped: 68 protected tests
failed: 0
errors: 0
warnings: 897

statements: 92,610
covered statements: 91,419
statement coverage: 98.71% (threshold 95.00%)
branches: 27,700
covered branches: 26,996
branch coverage: 97.18% (threshold 94.00%)

contract validation: PASS
schemas: 188
examples: 250
negative examples: 217
OpenAPI documents: 9
```

The Checkpoint policy intentionally skips protected PostgreSQL, browser, and
live-provider profiles. P8-S48 separately executed the protected actual
`nex_ae_test` + `nex_wc_test` smoke and verified migration, terminal decision,
append-once evidence persistence, exact replay, and cleanup.

## Evidence Integrity

Raw reports remain local under ignored `reports/` paths. Their hashes are:

```text
10e42045773b0235ebf4f42867e20c76127a53f23204fcb94b989dcc73b2f3dd  reports/quality/checkpoint.coverage.json
8d115d4db7e3cf3e849025720955d8f74d56573720a0d313a07e969d0f8cf5f3  reports/quality/checkpoint-latest.json
```

## Decision

P8-S44 through P8-S48 pass the repository Checkpoint Gate. The AE-owned
Platform ApprovalEvidence boundary and the S47 AE-to-WC HTTP edge are retained.
P8 may proceed to P8-S49 NSL ApprovalEvidence projection and verifier work.
