# GB2-CA00-S20A Coverage Margin and Active Runtime Branch Hardening

## Status

```text
Slice                         = GB2-CA00-S20A
Status                        = CLOSED
Database migration            = NONE
Business/API contract change  = NONE
Coverage thresholds changed   = NO
Repository Full Gate          = PASS
```

## Purpose

S20A restores margin above the canonical repository coverage floor without
changing the measured source roots, exclusions, or gate thresholds. It also
separates product-code coverage from smoke/test-harness coverage so that a
high aggregate no longer hides the ownership of remaining gaps.

The canonical thresholds remain:

```text
statement coverage >= 96.00%
branch coverage    >= 94.00%
```

## Source Audit and Refactoring

The audit identified three canonical installed-runtime smoke runners and two
active controlled-WRITE modules as the highest-value S20A targets:

```text
scripts/smoke/run_gb2_ca00_s05_ae_agent_runtime_worker.py
scripts/smoke/run_gb2_ca00_s06_wc_event_delivery_worker.py
scripts/smoke/run_gb2_ca00_s07_eos_outbox_publisher.py
services/_shared/nex_runtime/nsl_runtime_adapter.py
services/nex-ae-api/nex_ae_api/product_controlled_skill.py
```

The smoke runners previously assembled database/process orchestration and
acceptance decisions in one body. S20A extracted only pure component-evidence
builders. Database mutation, process composition, cleanup ownership, command
entrypoints, and protected-smoke behavior remain unchanged. WC/EOS status-code
checks now fail closed for an empty or malformed transport result instead of
raising an indexing error.

## Coverage Ownership Report

`scripts/quality/report_coverage_hotspots.py` consumes the canonical
coverage.py JSON and writes `reports/coverage/coverage-hotspots.json`. The
quality gate invokes it after the unchanged threshold checker.

The report exposes three non-overlapping ownership scopes:

| Scope | Files | Statements | Statement | Branch |
| --- | ---: | ---: | ---: | ---: |
| Product code (`services`, `providers`) | 679 | 108,605 | 98.24% | 96.59% |
| Smoke/test harness (`scripts/smoke`, `scripts/quality`) | 864 | 77,533 | 93.59% | 92.00% |
| Other runtime tooling | 26 | 3,256 | 93.77% | 84.99% |

It also records missing statement/branch counts, ranked file hotspots, and the
number of already-existing statements required for the 96.25% and 96.30%
targets. Generated reports remain under the intentionally ignored `reports/`
tree; this document is the durable evidence.

## Branch Hardening

Tests were added around denial and recovery behavior rather than padding only
the happy path:

- malformed NSL bindings, package identities, JSON, Skill results, and empty
  HTTP status tuples;
- payload-hash, attachment-manifest, and replay semantic conflicts;
- fresh OA authority success, missing evidence, and scope denial;
- WC work-result retryable storage failures, identity races, and lineage/time
  mapping failures;
- EOS authorization client configuration, timeout, network, HTTP, and JSON
  response classification;
- approval checkpoint persistence/reload, exact replay, collision rejection,
  and controlled-WRITE resume denial/approval;
- canonical runner PASS/FAIL exit mapping.

The active runtime modules now measure:

| Module | Statement | Branch | Missing statements/branches |
| --- | ---: | ---: | ---: |
| `nsl_runtime_adapter.py` | 99.31% | 96.67% | 1 / 1 |
| `product_controlled_skill.py` | 95.34% | 85.29% | 19 / 10 |

## DB-less Canonical Orchestration

The S05, S06, and S07 tests execute the real canonical runner orchestration
bodies with in-memory database/process/transport collaborators. They cover
construction, signed denial followed by retry, replay, restart, heartbeat,
ACK loss, and cleanup evidence without replacing the complete runner with a
mock. Protected PostgreSQL acceptance remains independently guarded and was
not weakened.

Canonical runner coverage after the Full Gate is:

| Runner | Statement | Branch | Missing statements/branches |
| --- | ---: | ---: | ---: |
| S05 AE runtime worker | 85.23% | 66.67% | 22 / 8 |
| S06 WC event delivery | 87.71% | 59.38% | 29 / 13 |
| S07 EOS outbox publisher | 90.05% | 69.23% | 21 / 8 |

## Verification

Focused regression before the Full Gate:

```text
125 passed
ruff check = PASS
compileall = PASS
```

Canonical Repository Full Gate:

```text
pytest                         = 18,783 passed / 133 skipped
failed                         = 0
statement coverage             = 182,310 / 189,394 = 96.2596%
branch coverage                = 41,169 / 43,204 = 95.2898%
statement minimum target       = 96.25% PASS
branch prior baseline          = 95.1440% PASS (+0.1458 percentage points)
contract validation            = PASS (227 / 291 / 245 / 10)
Full Gate exit code            = 0
```

The optional 96.30% upper target is not claimed: the report calculates that
77 additional existing statements would be required at the current
denominator. The required 96.25% target and the branch non-regression target
are both satisfied.

## Decision

GB2-CA00-S20A is closed. Coverage thresholds and source scope remain intact,
the repository has a repeatable ownership-aware hotspot report, active
runtime rejection/replay/recovery branches are hardened, and canonical smoke
orchestration has useful DB-less regression coverage.
