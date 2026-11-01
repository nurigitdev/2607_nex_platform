# GB2-CA00-S20J Coverage Hardening Closure and Repository Full Gate

**Status:** COMPLETE

**Date:** 2026-11-01

**Entry baseline:** `d20faf60`

## 1. Scope

This Slice closes the S20B-S20J coverage hardening sequence. It regenerates
the canonical ownership-aware coverage evidence, compares the result with the
S20A baseline, records the disposition of the remaining hotspots, and runs the
unchanged Repository Full Gate.

It does not change a database schema, public API, coverage source root,
coverage exclusion, or coverage threshold.

## 2. S20A-to-S20J Coverage Comparison

| Scope | Metric | S20A | S20J | Delta |
| --- | --- | ---: | ---: | ---: |
| Repository | files | 1,569 | 1,570 | +1 |
| Repository | statements | 189,394 | 189,406 | +12 |
| Repository | covered statements | 182,310 | 182,713 | +403 |
| Repository | missing statements | 7,084 | 6,693 | -391 |
| Repository | statement coverage | 96.2596% | 96.4663% | +0.2067 pp |
| Repository | branches | 43,204 | 43,214 | +10 |
| Repository | covered branches | 41,169 | 41,372 | +203 |
| Repository | missing branches | 2,035 | 1,842 | -193 |
| Repository | branch coverage | 95.2898% | 95.7375% | +0.4477 pp |
| Product code | files | 679 | 678 | -1 |
| Product code | statements | 108,605 | 108,516 | -89 |
| Product code | missing statements | 1,910 | 1,551 | -359 |
| Product code | statement coverage | 98.2413% | 98.5707% | +0.3294 pp |
| Product code | branches | 31,990 | 31,982 | -8 |
| Product code | missing branches | 1,090 | 912 | -178 |
| Product code | branch coverage | 96.5927% | 97.1484% | +0.5557 pp |
| Smoke/test harness | files | 864 | 866 | +2 |
| Smoke/test harness | statements | 77,533 | 77,634 | +101 |
| Smoke/test harness | missing statements | 4,971 | 4,939 | -32 |
| Smoke/test harness | statement coverage | 93.5885% | 93.6381% | +0.0496 pp |
| Smoke/test harness | branches | 10,528 | 10,546 | +18 |
| Smoke/test harness | missing branches | 842 | 827 | -15 |
| Smoke/test harness | branch coverage | 92.0023% | 92.1582% | +0.1559 pp |
| Other runtime tooling | statement coverage | 93.7654% | 93.7654% | unchanged |
| Other runtime tooling | branch coverage | 84.9854% | 84.9854% | unchanged |

Both optional statement targets recorded by the hotspot report are now met:

```text
additional existing statements required for 96.25% = 0
additional existing statements required for 96.30% = 0
```

## 3. Hotspot Disposition

### Resolved or hardened

- S20B hardened trust, approval, and fail-closed authorization branches.
- S20C hardened WC durable replay, conflict, and recovery branches.
- S20D hardened AE result finalization, publication, and ACK/replay branches.
- S20E hardened OA identity and EOS project/membership boundaries.
- S20F hardened retrieval, attachment, ingestion, and storage denial paths.
- S20G and S20H decomposed large canonical and operational smoke runners into
  testable orchestration helpers without weakening protected smoke behavior.
- S20I added focused AE/AG large-module branch tests and removed the obsolete
  `nex_wc.demo_runtime` implementation.

### Retained compatibility code

The following low-coverage modules remain deliberately isolated compatibility
boundaries and are not canonical product dependencies:

| Module | Statement / branch | Decision |
| --- | ---: | --- |
| `nex_ae_api/p8_demo_controlled_skill.py` | 49.80% / 26.92% | Retain for historical P8 controlled-WRITE replay. Do not add padding tests. |
| `nex_runtime/demo_nsl_runtime_adapter.py` | 29.60% / 22.22% | Retain for exact admitted NSL package replay. Do not add padding tests. |
| `run_p8_demo_s10b_installed_runtime.py` | harness hotspot | Retain historical evidence, rebound through canonical runtime composition. |

The demo/product dependency audit enforces that canonical product code does
not import these compatibility modules.

### Deferred active modules

`artifacts.py`, the artifact-retention scheduler pair, and the AG artifact and
operations projections remain large active modules. S20I found no bounded
extraction that would reduce meaningful complexity without moving lifecycle or
projection contracts. Their highest-risk rejection and recovery branches were
covered directly. A structural split is deferred until a responsibility gains
an independent API, persistence owner, or process lifecycle.

### Retained historical tooling

The largest remaining smoke runners and `run_p8_demo_tenant_fixture.py` are
historical or protected acceptance tooling. They remain outside canonical
runtime composition. Their low isolated percentages are visible in the
hotspot report and are not hidden by the repository aggregate.

## 4. Repository Full Gate Evidence

```text
command                         = scripts/quality/run_quality_gate.sh
exit code                       = 0
pytest                          = 18,897 passed / 133 skipped
failed                          = 0
statement coverage              = 182,713 / 189,406 = 96.4663%
branch coverage                 = 41,372 / 43,214 = 95.7375%
product statement / branch      = 98.5707% / 97.1484%
harness statement / branch      = 93.6381% / 92.1582%
contract validation             = PASS (227 schemas / 291 examples /
                                  245 negative examples / 10 OpenAPI)
golden transition audit         = PASS (9 registered / 1 enforced)
demo dependency audit           = PASS (680 product files / 6 wrappers /
                                  7 of 7 edges / 0 findings)
```

The generated canonical evidence is available under the intentionally ignored
`reports/coverage/` directory:

```text
coverage.json
coverage-hotspots.json
junit.xml
```

Protected remote embedding, reranking, generation, calibration, and model
rollout checks were explicitly skipped because remote providers are not
reachable in the current environment. This Slice does not claim remote live
acceptance. The Full Gate's local, contract, database-guarded, and DB-less
orchestration checks passed without requiring those providers.

## 5. Closure

The S20B-S20J sequence is closed. Repository and product coverage increased,
branch coverage did not regress, ownership-specific gaps remain visible, and
coverage thresholds and source scopes are unchanged. Remote-provider live
acceptance remains a separate protected run for an environment with provider
connectivity.
