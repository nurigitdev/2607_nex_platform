# P8-S32-S41 Checkpoint Gate Evidence

**Status:** PASS  
**Date:** 2026-10-22  
**Revision:** `1dc465f1ad705437127ae806f6c9ad3f2307b66f`  
**Branch:** `transition/p4-agent-runtime-foundation`  
**Host:** `tprover-X110`  
**Python:** `3.12.13`

## Purpose

This evidence closes the requested Checkpoint Gate after P8-S32 through
P8-S41. The covered implementation establishes a separate WC-owned human
approval aggregate, OA authorization, immutable decisions, transactional
outbox publication, EOS principal resolution, and authorized inbox/detail/
decision APIs without extending the existing delegation tables.

## Execution

The canonical Checkpoint wrapper was executed after P8-S41:

```text
scripts/quality/run_checkpoint_gate.sh

result: PASS
commands: 3/3
duration: 793.652 seconds
```

## Regression and Coverage

```text
passed: 15,383
skipped: 61 protected tests
failed: 0
errors: 0
warnings: 897

statements: 91,887
covered statements: 90,694
statement coverage: 98.70% (threshold 95.00%)
branches: 27,512
covered branches: 26,731
branch coverage: 97.16% (threshold 94.00%)

contract validation: PASS
schemas: 188
examples: 250
negative examples: 217
OpenAPI documents: 9
```

The protected PostgreSQL and browser profiles remain intentionally excluded
from this Checkpoint policy. Actual WC/OA PostgreSQL integration and the IA
approval experience remain assigned to the canonical P8-S43 acceptance
boundary; this result does not claim those checks were executed.

## Evidence Integrity

Raw reports remain local under ignored `reports/` paths. Their hashes at this
checkpoint are:

```text
8b3e0dcea68edab48b4493e185d008968cab39713d8c9d4ea3eaab88f6d900cd  reports/quality/checkpoint.coverage.json
6bf551964a4c956d2de1a0669631a301700611a8bff9d53ebb3ad7818e45ddda  reports/quality/checkpoint-latest.json
```

## Decision

P8-S32 through P8-S41 pass the repository Checkpoint Gate. The separate
approval-table design is retained, no corrective migration or source change
is required, and P8 may continue to the remaining P8.3 integration and
acceptance slices.
