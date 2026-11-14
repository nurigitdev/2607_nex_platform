# W60-S7-02A Deterministic Direct/Allocation Projector and Watermark Rebuild

## Decision

`W60-S7-02A` activates the deterministic rebuild path above the immutable
Project P&L persistence foundation. The projector reads existing EOS monetary
authorities and does not create another accounting source of record.

The authoritative classification boundary is `eos_cost_source_pool`:

- `DIRECT` means the source Project owns the eligible POSTED amount exactly
  once;
- `MANAGEMENT_ALLOCATION` means only `COMMITTED` allocation batches and their
  `ALLOCATED` lines enter confirmed Project allocation;
- the difference between eligible amount and committed allocation remains an
  explicit unallocated component on the source Project;
- `REVERSED` sources and non-committed allocation batches are excluded.

The projector does not reinterpret arbitrary Journal debit/credit lines. The
S6 SourcePool admission policy remains the eligibility, account-category,
Project/company, and direct-versus-allocation authority.

## Deterministic Rebuild

`ProjectPnlRebuildRequest` fixes tenant, company, Project, period, projection
version, functional currency, `as_of`, evaluation time, and stale threshold.
The rebuild produces:

- a deterministic UUIDv5 projection identity for the scope/version;
- source-set posting and allocation watermarks using canonical semantic hashes;
- stable component ordering and hashes;
- `CURRENT` or `STALE` freshness from the explicit evaluation time;
- `VERIFIED`, `PENDING`, `PARTIAL`, or `BLOCKED` reconciliation state;
- the immutable append/exact-replay behavior established in W60-S7-02.

The same sources, cutoff, and version produce the same draft, component order,
watermarks, projection ID, and semantic hash. A changed source set under an
already-used version conflicts rather than silently rewriting history.

## Classification and Conservation

The projector maps authoritative sources as follows:

| Source | Projection classification |
|---|---|
| DIRECT revenue | `POSTED_REVENUE` |
| DIRECT expense | `POSTED_DIRECT_COST` |
| Allocated expense | `POSTED_ALLOCATED_COST` |
| Allocated payroll | `POSTED_LABOR_ALLOCATED` |
| Payroll residue | `POSTED_PAYROLL_UNALLOCATED` |
| Other residue | `UNALLOCATED` |
| Realized FX source | `FX_REALIZED_GAIN_LOSS` |

Purchase sources are normalized to the P&L `MATERIAL` source kind. Payroll
components remain `PAYROLL_SENSITIVE`; other actual components are
`CONFIDENTIAL_FINANCIAL`.

Signed confirmed classifications now admit negative reversal/correction facts.
Cost/revenue reversals therefore reduce confirmed totals without using a fake
positive component. FX expense is represented as a signed loss.

For every management pool, committed allocations cannot exceed the eligible
amount in either positive or negative direction. Direct pools must already be
`ALLOCATED`. Duplicate pool/allocation identities, allocation against a direct
pool, an allocated pool without committed evidence, Project Code mismatch,
currency mismatch, or a source transition observed mid-read fail closed.

## Runtime Composition

The canonical EOS dependency factory now composes:

1. `SqlAlchemyEosProjectPnlProjectionSource`;
2. `SqlAlchemyEosProjectPnlRepository`;
3. `EosProjectPnlProjector`.

The projector is available through EOS app state for later worker/API Slices.
This Slice does not add a public HTTP route or event worker.

## Verification

Focused projector/persistence tests:

```text
tests                         = 68 passed
project_pnl + projector       = 99% statement / 99% branch
```

Adjacent budget, allocation-plan, and SourcePool regression:

```text
tests = 189 passed, 1 protected-smoke skip
```

Protected PostgreSQL smoke used the actual `nex_eos_test` database and an
isolated schema. It applied all EOS migrations through `2543`, then exercised
the existing product path rather than inserting P&L fixtures:

1. created a real governed VoucherCandidate and atomic POSTED Journal;
2. admitted the eligible expense Journal line as a management SourcePool;
3. released and executed a real two-Project allocation;
4. rebuilt the Project projection from the persisted SourcePool and committed
   allocation rows;
5. verified one-half allocated cost, zero residue, `VERIFIED` reconciliation,
   deterministic watermarks, and exact replay;
6. dropped the isolated schema and confirmed zero residue.

The first protected run intentionally used a cutoff one minute before the
Journal's fixed `posted_at`; the projector rejected the impossible
allocation-without-visible-source snapshot. Moving `as_of` to the actual
posting instant passed and proves historical cutoff enforcement.

```text
protected PostgreSQL smoke = 1 passed
```

Final NeX-EOS Slice Gate:

```text
tests               = 2027 passed, 59 protected-smoke skips
statement coverage  = 96.90% (threshold 95.00%)
branch coverage     = 95.09% (threshold 94.00%)
commands            = 5/5 passed
contract validation = PASS (264 schemas, 315 examples, 10 OpenAPI)
transition audit    = PASS
dependency audit    = PASS
```

Remote generation, embedding, and reranking providers were not used.

## Closure

```text
W60-S7-02A deterministic direct/allocation projector = PASS / CLOSED
```

Later payroll/material source adapters may add their watermarks and typed
components without changing this direct/allocation exclusivity or projection
version contract.
