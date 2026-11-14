# W60-S7-02B PayrollPostingEvidence and LaborEffortSnapshot Bridge

## Decision

`W60-S7-02B` adds the privacy-preserving bridge between an external
HR/payroll authority and EOS Project P&L. It does not create an HR, attendance,
tax, payslip, or employee-payroll source of record in EOS.

The bridge persists three append-only structures:

- `eos_payroll_post_evidence`: one exact eligible POSTED payroll-expense
  SourcePool component mapped to an opaque PayrollRun revision;
- `eos_labor_effort_snapshot`: one approved actual-effort or explicit
  approved-plan fallback snapshot; and
- `eos_labor_effort_line`: Project/WorkCode and approved non-identifying
  aggregate dimensions, effort units, population, and suppression metadata.

Employee ID, subject reference, salary, net pay, tax, deduction, bank account,
and individual payroll cost are not persisted in these structures.

## Payroll Posting Boundary

The caller supplies PayrollRun lineage, component classification, source and
approval hashes, and optional organization scope. Journal, line, account,
period, eligible amount, currency, and component identity are derived from the
existing `eos_cost_source_pool`; callers cannot restate those accounting
facts.

Admission requires:

- `source_kind = PAYROLL`;
- an eligible `EXPENSE` component;
- a pool that is not `REVERSED` or `ON_HOLD`;
- a canonical component class; and
- immutable source, approval, mapping, and evidence hashes.

Liability, withholding, cash, net-pay, advance, balancing, or asset lines
therefore cannot enter through this bridge unless they have incorrectly
passed the earlier SourcePool accounting admission boundary.

## Labor Effort Boundary

`ACTUAL_APPROVED` accepts an external approved source reference/hash and
Project-level aggregate effort. `APPROVED_PLAN_FALLBACK` is deliberately
narrower:

- the unit must be `MAN_DAY`;
- every line must resolve to an existing HUMAN WorkAssignment;
- Project, WorkCode, validity period, planned Man-Day, assignment hash, and
  planned Grade must match exactly; and
- the result remains a plan fallback for a later allocation Slice to classify
  as provisional, never confirmed actual effort.

Project membership is not read and cannot become an effort ratio. Project and
approved company binding must cover the complete effort period, and the
Project must be `ACTIVE` or `CLOSING`.

Each line records population and minimum-population metadata. Small cells are
marked `ordinary_view_suppressed`; S7-03 remains responsible for authorized
query shaping and inference prevention.

## Immutability And Replay

Payroll evidence and effort snapshot identities use deterministic UUIDv5 and
domain-separated semantic hashes. Exact replay returns the existing record;
the same identity with different semantics fails with conflict.

PostgreSQL triggers reject `UPDATE` and `DELETE` on all three bridge tables.
Late payroll or work correction must therefore create a new revision. The
existing Project P&L, SourcePool, WorkAssignment, Journal, and allocation
authorities remain unchanged.

Migration `2544_eos_payroll_labor_bridge.sql` is the new EOS migration head.
All table, index, trigger, and constraint identifiers remain within the
PostgreSQL identifier limit.

## Runtime Composition

The canonical EOS dependency factory now composes
`EosPayrollLaborBridgeService` and exposes it through application state. This
Slice intentionally adds no public HTTP route and does not yet create payroll
allocation lines or P&L components. The following Slice may consume this
bridge to build a governed allocation plan while preserving the existing
direct/allocation exclusivity and projector watermarks.

## Verification

Focused payroll/labor bridge tests:

```text
tests                  = 50 passed
bridge statement/branch combined coverage = 98%
```

Adjacent P&L, projector, WorkAssignment, and SourcePool regression:

```text
tests = 156 passed, 2 protected-smoke skips
```

Protected PostgreSQL smoke used the actual `nex_eos_test` database and an
isolated schema. It:

1. applied all EOS migrations through `2544`;
2. created a real governed VoucherCandidate and atomic POSTED Journal;
3. admitted its expense line as a PAYROLL SourcePool;
4. persisted and replayed PayrollPostingEvidence from that exact component;
5. persisted and replayed an approved actual LaborEffortSnapshot;
6. verified small-cell suppression metadata and absence of employee-payroll
   columns;
7. proved the database mutation trigger rejects evidence updates; and
8. dropped the isolated schema and confirmed zero residue.

```text
protected PostgreSQL smoke = 1 passed
```

Final NeX-EOS Slice Gate:

```text
tests               = 2077 passed, 60 protected-smoke skips
statement coverage  = 96.92% (previous 96.90%, threshold 95.00%)
branch coverage     = 95.18% (previous 95.09%, threshold 94.00%)
commands            = 5/5 passed
contract validation = PASS (264 schemas, 315 examples, 10 OpenAPI)
transition audit    = PASS
dependency audit    = PASS
```

Remote generation, embedding, and reranking providers were not used.

## Closure

```text
W60-S7-02B PayrollPostingEvidence/LaborEffortSnapshot bridge = PASS / CLOSED
```

Payroll allocation, provisional-to-actual replacement, residual labor
treatment, and projection watermark consumption remain subsequent W60 work.
