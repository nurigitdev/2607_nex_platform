# GB2-CA00 Post-S20A Coverage Hardening Execution Plan v1.0

**Status:** PLANNED / SOURCE-BACKED / POST-CLOSURE QUALITY HARDENING

**Program:** NeX Platform v2.1

**Parent baseline:** GB2-CA00-S20A Coverage Margin and Active Runtime Branch Hardening

**Branch:** `transition/p4-agent-runtime-foundation`

**Observed baseline commit:** `70fee994`

**Observed date:** 2026-11-01

## 1. Purpose

This plan records the execution order for the coverage gaps that remain after
GB2-CA00-S20A. The objective is not to increase a repository percentage by
padding tests. The objective is to reduce unverified behavior in active
trust, authorization, durable workflow, replay, conflict, and recovery
boundaries before further Golden B v2 implementation.

The accepted GB2-CA00 As-Built remains closed. This work is a post-closure
quality-hardening sequence and does not reopen the runtime topology decision.

## 2. Source-Backed Baseline

The canonical S20A coverage report records:

| Scope | Files | Statements | Missing statements | Statement | Branches | Missing branches | Branch |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Product code | 679 | 108,605 | 1,910 | 98.24% | 31,990 | 1,090 | 96.59% |
| Smoke/test harness | 864 | 77,533 | 4,971 | 93.59% | 10,528 | 842 | 92.00% |
| Other runtime tooling | 26 | 3,256 | 203 | 93.77% | 686 | 103 | 84.99% |
| Repository total | 1,569 | 189,394 | 7,084 | 96.2596% | 43,204 | 2,035 | 95.2898% |

Gap concentration is sufficient for focused hardening:

```text
Product top 20 hotspots
  = 52.6% of missing product statements

Smoke/test-harness top 20 hotspots
  = 50.3% of missing harness statements
```

## 3. Prioritization Rules

Candidates are ordered by:

```text
active installed use
  x security/business consequence
  x uncovered denial/replay/conflict/recovery branches
  x deterministic testability
```

Absolute missing-line count alone is not a sufficient reason to change a
module. In particular:

- an active trust boundary with 17 missing statements may precede a large
  module with 133 scattered missing statements;
- protected smoke code shall not be executed in every Full Gate only to
  increase coverage;
- historical Demo code shall not receive coverage-padding tests before its
  retain/rebind/retire status is decided;
- large modules shall receive a responsibility-boundary audit before broad
  refactoring;
- coverage roots, exclusions, and canonical thresholds remain unchanged.

## 4. Canonical Execution Order

### GB2-CA00-S20B: Product Trust and Approval Boundary Hardening

Primary modules:

```text
services/_shared/nex_runtime/nsl_runtime_bundle.py
services/nex-eos/nex_eos/approval_decision_api.py
services/nex-ae-api/nex_ae_api/approval_decision_event_api.py
```

Required coverage:

- malformed bundle manifest, path escape, wheel identity, digest, schema, and
  timestamp rejection;
- missing caller/service identity, invalid payload/UUID/lineage, denied
  authority, and typed approval-transition failures;
- fail-closed behavior without DB migration or public API shape changes.

Gate: focused unit regression, contract checks, and Slice Gate.

### GB2-CA00-S20C: WC Durable Coordination and Work-Result Hardening

Primary modules:

```text
services/nex-wc/nex_wc/coordination.py
services/nex-wc/nex_wc/work_results.py
```

Required coverage:

- semantic replay, requester mismatch, claim/assignment conflict, duplicate
  settlement, stale state, and malformed identity;
- SQL integrity race, retryable storage failure, rollback, mapping, and
  timestamp conversion;
- focused PostgreSQL smoke for behavior that SQLite cannot prove.

Gate: focused regression, actual WC test-DB protected smoke, and Slice Gate.

### GB2-CA00-S20D: AE Result Resume and Publication Hardening

Primary modules:

```text
services/nex-ae-api/nex_ae_api/work_result_events.py
services/nex-ae-api/nex_ae_api/workspace_result_publication.py
```

Required coverage:

- parent-not-ready, malformed event, unsupported transition, and storage
  failure classification;
- publication ACK conflict, duplicate completion, notifier failure, candidate
  query failure, finalization failure, and restart-safe replay;
- no duplicate AgentResult or user-visible workspace result.

Gate: focused regression, actual AE test-DB protected smoke where needed, and
Slice Gate.

### GB2-CA00-S20E: OA Identity and EOS Project Boundary Hardening

Primary modules:

```text
services/nex-oa/nex_oa/subjects.py
services/nex-eos/nex_eos/project_operations.py
```

Required coverage:

- subject integrity conflict, inactive/missing subject, metadata validation,
  JSON/datetime conversion, and repository failure;
- tenant/owner denial, project replay/conflict, membership identity failure,
  and zero-mutation rejection;
- preserve the current OA and EOS persistence contracts.

Gate: focused regression, actual OA/EOS test-DB protected smoke, and Slice
Gate.

### GB2-CA00-S20F: Retrieval, Attachment, and Ingestion Edge Hardening

Primary modules:

```text
services/nex-ag/nex_ag/retrieval_operations.py
services/nex-ae-api/nex_ae_api/voucher_attachments.py
services/nex-cx/nex_cx/ingestion.py
```

Required coverage:

- permission denial, no-answer/low-confidence, malformed retrieval evidence,
  and provider/storage failure classification;
- attachment manifest mismatch, cross-tenant access, duplicate/replay, and
  cleanup failure;
- ingestion identity conflict, stale/retry transitions, malformed artifacts,
  and restart-safe recovery.

Gate: focused regression, applicable protected smoke, then the fifth-Slice
Checkpoint Gate covering S20B through S20F.

### GB2-CA00-S20G: Canonical Journey Harness Decomposition

Primary runners:

```text
scripts/smoke/run_p8_s53_approval_resume_postgres.py
scripts/smoke/run_platform_authenticated_ingestion_postgres_smoke.py
scripts/smoke/run_p8_s112_nvt_membership_acceptance.py
```

Required change shape:

- extract scenario, command, transition, cleanup, and evidence decisions into
  deterministic helpers;
- inject DB/process/provider/browser collaborators at narrow boundaries;
- add DB-less orchestration tests for denial, malformed response, retry,
  cleanup, and exit-code mapping;
- retain the real protected PostgreSQL/provider/Playwright entrypoints.

Gate: focused harness regression and Slice Gate. A protected environment is
not required merely to exercise deterministic orchestration branches.

### GB2-CA00-S20H: Operational Recovery Harness Decomposition

Primary runners:

```text
scripts/smoke/run_s146_object_storage_acceptance.py
scripts/smoke/run_s145_postgresql_recovery_acceptance.py
scripts/smoke/run_platform_oa_backed_trust_postgres_smoke.py
```

Required change shape:

- isolate object-storage tenant/readback/cleanup decisions;
- isolate PostgreSQL recovery command planning, fingerprint validation,
  rollback, and fail-closed evidence decisions;
- isolate signed-trust admission, denial, expiry, and cleanup orchestration;
- preserve actual protected RustFS/PostgreSQL/OA acceptance separately.

Gate: focused harness regression, applicable protected smoke, and Slice Gate.

### GB2-CA00-S20I: Demo Residue and Large-Module Structural Audit

Demo candidates:

```text
services/nex-ae-api/nex_ae_api/p8_demo_controlled_skill.py
services/_shared/nex_runtime/demo_nsl_runtime_adapter.py
services/nex-wc/nex_wc/demo_runtime.py
scripts/smoke/run_p8_demo_s10b_installed_runtime.py
```

Large active candidates:

```text
services/nex-ae-api/nex_ae_api/artifacts.py
services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py
services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py
services/nex-ag/nex_ag/artifact_operations.py
services/nex-ag/nex_ag/operations.py
```

Required decisions:

- classify every Demo candidate as `RETAIN_COMPATIBILITY`,
  `REBIND_CANONICAL`, or `RETIRE`;
- prohibit canonical deployment dependencies on Demo-only modules;
- map large-module missing branches by responsibility and operational risk;
- refactor only where a bounded responsibility split removes meaningful
  complexity; otherwise add narrow high-value branch tests;
- do not add broad tests solely to keep dead compatibility code measured.

Gate: static dependency audit, focused regression for any changed module, and
Slice Gate.

### GB2-CA00-S20J: Coverage Hardening Closure and Repository Full Gate

Required closure:

- regenerate `coverage.json` and `coverage-hotspots.json`;
- compare product, harness, tooling, and repository scopes against the S20A
  baseline;
- record resolved, deferred, retained, and retired hotspots;
- run the canonical Repository Full Gate;
- publish a durable Slice record with exact test, coverage, contract, and
  protected-smoke evidence.

Gate: Repository Full Gate and `git diff --check`.

## 5. Coverage Acceptance

The canonical hard thresholds remain unchanged:

```text
repository statement >= 96.00%
repository branch    >= 94.00%
```

This sequence additionally uses the S20A observed values as non-regression
baselines unless a deliberate source-removal/refactoring delta is documented:

```text
product statement    >= 98.24%
product branch       >= 96.59%
harness statement    >= 93.59%
harness branch       >= 92.00%
repository statement >= 96.2596%
repository branch    >= 95.2898%
```

The intended closure target is repository statement coverage of at least
`96.30%`, but no security, persistence, or runtime boundary may be weakened to
reach it.

## 6. Testing Strategy

Every implementation Slice follows:

```text
source/refactoring audit
  -> focused unit tests
  -> focused owner regression
  -> applicable contract/static checks
  -> protected smoke only when environment semantics matter
  -> Slice Gate
```

Gate cadence:

```text
after S20F  = fifth-Slice Checkpoint Gate
after S20J  = Repository Full Gate
```

Actual PostgreSQL is required for transaction, concurrency, dialect, and
restart claims. RustFS, remote providers, and Playwright are required only for
the Slices whose acceptance claims depend on those environments. Unit and
DB-less orchestration tests remain the primary mechanism for deterministic
failure-branch coverage.

## 7. Non-Goals

This sequence does not authorize:

- changing coverage exclusions or lowering thresholds;
- adding new business capabilities;
- changing public API contracts without a separately approved decision;
- adding database tables merely to improve testability;
- replacing protected smoke with mocks;
- turning historical Demo fixtures back into installed runtime dependencies;
- broad refactoring of already high-coverage modules without a bounded
  structural reason.

## 8. Entry Decision

Implementation begins with `GB2-CA00-S20B`. Each Slice shall be completed and
verified before the next Slice starts. A contract change, migration need,
canonical deployment dependency on Demo code, or ambiguous ownership decision
is a stop condition requiring review.
