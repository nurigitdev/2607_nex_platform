# GB2-CA00-S20I Demo Residue and Large-Module Structural Audit

**Status:** COMPLETE

**Date:** 2026-11-01

**Entry baseline:** `79a2d417`

## 1. Scope

This Slice classifies the remaining named Demo candidates, makes the
classification machine-checkable, and audits the largest active AE/AG
coverage hotspots before deciding whether structural refactoring is justified.
It does not change a public API, database schema, deployment topology, or
remote-provider contract.

## 2. Demo Candidate Decisions

| Candidate | Decision | Result |
| --- | --- | --- |
| `nex_ae_api/p8_demo_controlled_skill.py` | `RETAIN_COMPATIBILITY` | Retained only for historical P8 controlled-WRITE replay. Canonical product code may not depend on it. |
| `nex_runtime/demo_nsl_runtime_adapter.py` | `RETAIN_COMPATIBILITY` | Retained for exact admitted NSL package replay. It is an explicit compatibility wrapper. |
| `nex_wc/demo_runtime.py` | `RETIRE` | Removed. `nex_wc.event_delivery_process` is the authoritative installed worker and already owns the same runtime responsibility. |
| `run_p8_demo_s10b_installed_runtime.py` | `REBIND_CANONICAL` | Retained as historical acceptance evidence whose implementation is bound to canonical AE runtime composition. |

`run_demo_product_dependency_audit.py` now fails closed when a retained or
rebound candidate disappears, when a retired candidate returns, or when
canonical product code imports a Demo-only module. The audit output includes
the decision, rationale, and current status of every candidate.

The historical Demo manifest regression no longer imports or exercises the
retired WC implementation. Its WC process binding continues to assert the
canonical `nex_wc.event_delivery_process` entrypoint.

## 3. Large-Module Responsibility and Risk Map

The S20A baseline is the source of the percentages and missing counts below.

| Module | Baseline statement / branch | Primary responsibility | Highest remaining operational risk | Decision |
| --- | ---: | --- | --- | --- |
| `nex_ae_api/artifacts.py` | 96.26% / 93.26% | artifact persistence, rendering, retention, object storage | storage retry/integrity classification and owner-private materialization | Keep structure; directly cover fail-closed object-storage mapping. |
| `nex_ae_api/artifact_retention_scheduler.py` | 97.21% / 93.63% | scheduling, lease, bounded loop, heartbeat | invalid daemon state and shutdown/heartbeat validation | Defer split; validators share the scheduler state contract and already have high statement coverage. |
| `nex_ae_api/artifact_retention_scheduler_daemon.py` | 98.28% / 95.86% | daemon CLI, supervisor control, run persistence | malformed operator/supervisor state conversion | Retain; a split would add cross-module lifecycle coupling for little risk reduction. |
| `nex_ag/artifact_operations.py` | 98.05% / 93.01% | read-only artifact operations and retention projections | cross-owner scheduled-job filtering and sparse operational summaries | Keep structure; directly cover every owner-scope rejection branch. |
| `nex_ag/operations.py` | 98.93% / 95.89% | unified operations projections and operator guidance | incomplete remediation sync-state runbook/action guidance | Keep structure; directly cover failure, missing, orphan, divergence, and unknown-state guidance. |

No bounded extraction was found that would reduce meaningful complexity
without moving public projection or lifecycle contracts. Broad refactoring is
therefore deferred. A future split is justified only when one of these
responsibilities gains an independent API, persistence owner, or process
lifecycle.

## 4. Focused Branch Hardening

- AE object-storage errors now have direct regression coverage for retryable
  unavailability, integrity conflicts, and terminal internal failures without
  leaking private provider details.
- AG retention scheduled-job filtering now covers wrong job type, malformed
  payload, tenant mismatch, workspace mismatch, owner mismatch, and status
  mismatch.
- AG remediation guidance now covers failed execution, missing execution,
  orphan execution, sync-required and terminal divergence, and unknown
  execution status for both runbooks and operator actions.

## 5. Verification

```text
focused regression
  40 passed

demo/product dependency audit
  status=PASS
  canonical product files=680
  explicit compatibility wrappers=6
  canonical compatibility edges=7/7
  findings=0

platform Slice Gate
  pytest=427 passed, 8 protected skips
  audit statement=100.00%
  audit branch=100.00%
  contract validation=PASS (227 schemas / 291 examples /
    245 negative examples / 10 OpenAPI documents)
  golden-journey transition audit=PASS
  commands=6/6
```

The protected skips are PostgreSQL topology and restart checks outside the
claims of this Slice and are not represented as live evidence. No remote
embedding, reranking, or generation provider was used or required.

## 6. Closure

The platform Slice Gate passed. S20I is closed after `git diff --check`, commit,
and push. S20J may then regenerate canonical coverage evidence and run the
Repository Full Gate.
