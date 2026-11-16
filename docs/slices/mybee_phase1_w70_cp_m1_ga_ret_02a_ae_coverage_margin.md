# CP-M1-GA-RET-02A.5: Coverage Margin Closure and Public M1 E2E Resume Decision

## Status

- State: `CLOSED`
- Date: `2026-11-16`
- Parent: `CP-M1-GA-RET-02A`
- Entry commit: `c8e69596`
- Product source change: none
- Database migration: none
- Public API change: none
- Remote provider: not required
- Public M1 E2E entry: `ADMITTED`

## Goal

Close the AE coverage-ownership and margin work after A0-A4, prove that the
corrective targets are met without weakening the canonical measurement, and
decide whether the original public M1 E2E may resume. This decision admits the
next test boundary; it does not claim that the public journey has passed.

## Completed Work Ledger

| Slice | Closed boundary |
| --- | --- |
| `A.0` | Extracted scenario-neutral controlled-Skill runtime and removed recursive active imports of Golden A history. |
| `A.1` | Classified all 176 AE modules and froze the semantic-hash-bound ownership inventory. |
| `A.2` | Admitted six exact cross-namespace AE-owned tests with deterministic selection and deduplication. |
| `A.3` | Added the mandatory ownership reporter as the sixth AE Gate command and fail-closed quarantine checks. |
| `A.4` | Hardened active Project-delegation denial, ambiguity, malformed-input and dependency-failure branches to `100% / 100%`. |
| `A.5` | Re-ran focused regression and the canonical AE Gate, classified residual hotspots, and admitted the public M1 E2E entry. |

## Final Coverage

| Metric | A.0 baseline | A.5 closure | Delta | Closure margin |
| --- | ---: | ---: | ---: | ---: |
| Aggregate statement | 95.8986% | 96.4497% | +0.5511 pp | +0.1997 pp over 96.25% target |
| Aggregate branch | 94.0503% | 94.6630% | +0.6127 pp | +0.1630 pp over 94.50% target |
| Canonical statement floor | 95.0000% | 96.4497% | - | +1.4497 pp |
| Canonical branch floor | 94.0000% | 94.6630% | - | +0.6630 pp |
| Active product statement | - | 97.1306% | - | separately visible |
| Active product branch | - | 94.9836% | - | separately visible |
| Historical statement / branch | 86.8421% / 81.7647% | unchanged | 0 | quarantined |

The canonical source root, hard floors, and aggregate denominator were not
reduced. All 176 modules are classified, all classified coverage modules are
reported, and historical active-import and deployment conflicts remain zero.

## Hotspot Disposition

### Resolved

- `project_delegation_planning.py`: statement and branch `100% / 100%`.
- Explicit AE test ownership: six exact transition tests are admitted without
  broad MyBee or Platform test selection.
- Ownership reporting: active product, active compatibility, and historical
  quarantine remain separately observable in every AE Slice Gate.

### Retained

- Large active modules such as `artifacts.py` and artifact-retention runtime
  remain in the complete AE denominator. Their current uncovered branches do
  not block this narrow corrective target and were not padded with duplicate
  happy-path tests.
- Active compatibility modules remain measurable. This Slice does not hide or
  physically relocate them.

### Deferred

- `product_capability_retirements.py`, `approval_decision_event_api.py`,
  `wa_source_projections.py`, and `eos_outbox_event_api.py` require their own
  product/API ownership and retirement decisions before focused hardening.
- Physical relocation of historical source and retirement of active
  compatibility wrappers remain separate work.

### Historical

The five hash-pinned modules remain in `HISTORICAL_QUARANTINE` and are absent
from the recursive active import graph and canonical deployment inputs:

```text
domain_intent_products.py
finance_golden_a_activation.py
golden_a_planning.py
mybee_product_consumer.py
product_controlled_skill.py
```

## Acceptance

| Criterion | Result |
| --- | --- |
| Explicit AE test ownership is Gate-protected | PASS |
| Unrelated MyBee/Platform tests are not broadly selected | PASS |
| Golden A history is absent from active imports and deployment | PASS |
| Active and historical coverage are separately visible | PASS |
| Project-delegation denial and ambiguity are covered | PASS |
| Aggregate statement is at least 96.25% | PASS, 96.4497% |
| Aggregate branch is at least 94.50% | PASS, 94.6630% |
| Canonical floors and source roots are unchanged | PASS |
| Focused regression, canonical AE Gate, and diff check pass | PASS |
| Resolved, retained, deferred, and historical hotspots are durable | PASS |

## Verification

```text
focused Ruff and regression             PASS, 83 tests
AE Slice Gate                           PASS, 6 / 6 commands
AE Slice Gate tests/files               6,228 passed / 46 protected skips, 434 files
AE Slice Gate duration                  503.068 seconds
aggregate statement / branch            96.4497% / 94.6630%
active product statement / branch       97.1306% / 94.9836%
historical statement / branch           86.8421% / 81.7647%
ownership inventory                     176 modules
active import modules                    69
ownership and quarantine checks          7 / 7, PASS
historical active/deployment conflicts   0 / 0
```

Generated evidence remains under ignored report paths:

```text
reports/quality/mybee-w70-ga-ret-02a-ae.coverage.json
reports/coverage/mybee-w70-ga-ret-02a-ae-ownership-hotspots.json
reports/coverage/mybee-w70-ga-ret-02a-ae.coverage.report_ae_coverage_ownership.json
reports/quality/slice-latest.json
```

## Resume Decision

`CP-M1-GA-RET-02A` is closed and the original `CP-M1-E2E-FX-01` public M1 E2E
may resume. The next Slice must use the generalized installed runtime and the
current D04/D12 Product Capability Registry. Golden A cannot return as an
active selector, consumer, fixture dependency, rollback profile, or deployment
input.

The public M1 E2E remains responsible for its own OA/AE/WC/EOS PostgreSQL,
signed trust, live generation, installed runtime, and Playwright acceptance.
