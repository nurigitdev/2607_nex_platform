# MyBee Phase 1 S6-03 Deterministic Allocation Batch and Reconciliation

## Status

```text
Slice = W50-CA01-S6-03
Decision = PASS / CLOSED
Date = 2026-11-13
Owner = NeX-EOS
Remote provider required = NO
Database migration = NO (reuse 2541 foundation)
```

## Objective

S6-03 activates the deterministic allocation batch and reconciliation
foundation reserved by migration `2541_eos_cost_source_allocation.sql`.
Approved S6-02 plan revisions now consume exact S6-01
`MANAGEMENT_ALLOCATION` SourcePools in one EOS transaction while preserving
signed amount conservation:

```text
Eligible = Direct + Allocated + Unallocated
E = D + A + U
```

This Slice does not create GL transfer Journals or mutate a committed
allocation. A later reversal is exposed as `ADJUSTMENT_REQUIRED`; the
immutable adjustment and GL transfer flow remains a subsequent W50 boundary.

## Source And Structure Audit

The existing migration already defines the canonical structures:

```text
eos_cost_allocation_batch
eos_cost_allocation_line
eos_cost_allocation_adjustment
```

No new table or migration was required. S6-03 reuses the shared EOS
`SqlAlchemyEosBusinessTransactionCoordinator`, so BusinessOperation,
idempotency, allocation batch and lines, SourcePool transition, and typed
outbox event commit atomically.

The batch's nullable `outbox_event_id` remains reserved for a future direct
event-key materialization. Current authoritative linkage is the immutable
`business_operation_id`; reconciliation resolves the unique outbox row by
that identity and typed event kind rather than maintaining a second mutable
pointer.

## Deterministic Policy

The execution policy is fixed as follows:

1. lock the AccountingPeriod, exact approved plan revision, and sorted source
   pools;
2. admit only `OPEN` `MANAGEMENT_ALLOCATION` pools with matching period,
   source kind, currency, recognition date, and plan effective date;
3. preserve signed positive and negative functional amounts at scale 4;
4. calculate exact shares using the approved plan ratios;
5. truncate each share toward zero at scale 4;
6. assign remaining `0.0001` units in stable
   `(basis_priority, project_id, work_code)` order;
7. persist every rounding delta and line evidence hash;
8. require exact source, allocated, and unallocated conservation before
   commit;
9. transition every consumed pool from `OPEN` to `ALLOCATED` in the same
   transaction;
10. reject changed identity, changed semantics, or concurrent state drift.

`DIRECT` pools remain terminal at S6-01 and cannot enter an S6-03 batch.
`GL_COST_TRANSFER` is not activated by this Slice.

## API And Contracts

```text
POST /internal/v2/finance/cost-allocation-batches
  operation = FINANCE.COST_ALLOCATION.RUN
  business scope = finance:allocation:execute

GET /internal/v2/finance/cost-allocation-batches/{batch_id}/verification
  operation = FINANCE.COST_ALLOCATION.VERIFY
  business scope = finance:allocation:verify
```

Both routes require an admitted signed service token for audience `nex-eos`.
`RUN` is a WRITE route; `VERIFY` is side-effect free.

Canonical contracts:

- `cost_allocation_run.v1.schema.json`
- `cost_allocation_batch.v1.schema.json`
- `cost_allocation_reconciliation.v1.schema.json`
- `cost_allocation_committed_event.v1.schema.json`

The typed `FINANCE.COST_ALLOCATION_COMMITTED.v1` event contains only company,
batch, plan, period, source-set, reconciliation, operation, and timestamp
lineage. It contains no employee or private payroll data.

## Reconciliation Semantics

`FINANCE.COST_ALLOCATION.VERIFY` reconstructs and checks:

- BusinessOperation and idempotency identity;
- committed batch, exact plan revision, lines, and source pools;
- source-set hash and every line evidence hash;
- signed `E=D+A+U` conservation and aggregate totals;
- result JSON and typed outbox event identity;
- pool reversal state.

The read model reports:

| Persisted state | Result |
|---|---|
| `PENDING` | `RECONCILIATION_REQUIRED` |
| `NOT_COMMITTED` | `NOT_COMMITTED_CONFIRMED`, same identity may retry |
| exact committed lineage | `VERIFIED`, do not rerun |
| committed lineage drift | `FAILED`, do not rerun |
| exact committed lineage with reversed pool | `ADJUSTMENT_REQUIRED` |

## Actual PostgreSQL Protected Smoke

The protected smoke connected directly to:

```text
database = nex_eos_test
role     = nex_eos_user
```

It performed the following real sequence in an isolated schema:

1. applied the complete EOS migration inventory through `2541`;
2. created a real VoucherCandidate and immutable PostedJournal;
3. admitted its expense line as a real `MANAGEMENT_ALLOCATION` SourcePool;
4. created a two-target approved allocation plan;
5. injected an invalid second allocation line and proved rollback of the
   BusinessOperation, idempotency, batch, lines, pool transition, and outbox;
6. issued the same valid command concurrently 20 times;
7. observed exactly `1 CREATED + 19 EXACT_REPLAY`;
8. verified exactly one batch, two lines, one typed allocation outbox event,
   and an `ALLOCATED` source pool;
9. ran persisted reconciliation and received `VERIFIED`;
10. dropped the isolated schema and verified zero residue.

```text
protected PostgreSQL smoke = 1 passed
```

Remote generation, embedding, and reranking providers were not used.

## Regression And Coverage

Focused implementation tests:

```text
tests                                      = 61 passed
new allocation modules statement coverage = 99.07%
new allocation modules branch coverage    = 95.51%
```

Adjacent S6 regression:

```text
tests = 132 passed, 2 protected-smoke skips
contract validation = PASS
schemas = 263, examples = 313, OpenAPI = 10
```

Final EOS Slice Gate:

```text
tests               = 1909 passed, 56 protected-smoke skips
statement coverage  = 96.92% (threshold 95.00%)
branch coverage     = 95.24% (threshold 94.00%)
commands            = 5/5 passed
contract validation = PASS
transition audit    = PASS
dependency audit    = PASS
```

W50 Checkpoint Gate initially identified repository-baseline drift rather than
allocation behavior defects. The checkpoint reconciliation updated:

- the pinned NeX-EOS OpenAPI digest after S6-03 contract admission;
- the NeX-EOS migration head from `2540` to the already-admitted `2541`;
- the contract example index for the two S6-01 SourcePool examples.

The affected baseline tests passed `32/32` before the canonical checkpoint was
re-run:

```text
repository tests     = 21299 passed, 169 protected-smoke skips
statement coverage   = 98.49% (threshold 95.00%)
branch coverage      = 97.06% (threshold 94.00%)
commands             = 5/5 passed
contract validation  = PASS (263 schemas, 315 examples, 10 OpenAPI)
transition audit     = PASS
dependency audit     = PASS
checkpoint duration  = 1904.486 seconds
```

## Entry Decision

```text
S6-03 deterministic allocation and reconciliation = PASS / CLOSED
```

The W50 flow may proceed to source-adapter and downstream Project P&L work.
Those later Slices must consume this immutable batch lineage and must not
recalculate or silently overwrite committed allocation amounts.
