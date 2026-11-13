# S6-01 POSTED GL SourcePool Eligibility

## Outcome

PASS / CLOSED. NeX-EOS now admits only verified, eligible components of an
immutable `POSTED` Journal into an authoritative Cost SourcePool. The boundary
preserves mandatory Project attribution while preventing cash, liability,
equity, inventory/asset, and deferred-cost lines from becoming Project P&L
merely because their Journal line carries a Project Code.

## Source Audit Decision

SourcePool admission does not accept caller-supplied amounts, accounts,
currencies, Projects, or FX values. The service derives all financial facts
from the exact immutable Journal header and line and verifies the committed
Posting through `EosJournalOperationService` before persistence.

The admission additionally requires:

- the exact Journal line's account and company policy snapshots;
- matching Posting rule and account-policy release hashes;
- the user-facing Project Code and internal Project UUID from the Journal;
- an effective, approved Project-company binding on recognition date;
- an `ACTIVE` or `CLOSING` source Project;
- booked functional-currency debit/credit amounts, never a reconstructed
  market or cash value.

The eligible component identity is currently one deterministic account
component per Journal line:

```text
ACCOUNT:{account_id}
```

This is deliberately narrower than accepting an arbitrary component identity
from the caller. A later admitted source adapter may add finer component
lineage without weakening the existing uniqueness boundary.

## Recognition Classification

The caller must explicitly select one active Phase-1 recognition path:

| Mode | Initial pool state | Meaning |
|---|---|---|
| `DIRECT` | `ALLOCATED` | The source Project already owns the recognized amount; it must not be allocated again. |
| `MANAGEMENT_ALLOCATION` | `OPEN` | The source amount awaits an approved S6-02 plan and S6-03 allocation batch. |

`GL_COST_TRANSFER` remains represented in the persistence foundation but is
not admitted by the S6-01 runtime. Changing the source kind or recognition
mode for an already admitted Journal component returns conflict rather than
silently rewriting financial meaning.

Expense source kinds require an `EXPENSE` account. `REVENUE` requires a
`REVENUE` account. `FX_GAIN_LOSS` accepts either category and preserves the
booked signed functional amount. `ASSET`, `LIABILITY`, and `EQUITY` accounts
fail closed.

## Persistence Foundation

Migration `2541_eos_cost_source_allocation.sql` creates the normalized W50
foundation reserved by W50-CA01:

```text
eos_cost_source_pool
eos_cost_allocation_plan
eos_cost_allocation_plan_line
eos_cost_allocation_batch
eos_cost_allocation_line
eos_cost_allocation_adjustment
```

Only `eos_cost_source_pool` is active in this Slice. The other tables reserve
the immutable plan, execution, result, and adjustment boundaries for S6-02 and
S6-03; their runtime behavior is not claimed here.

Source uniqueness is enforced by:

```text
(tenant_id, company_id, journal_id, journal_line_no, eligible_component_id)
```

The deterministic pool UUID and domain-separated semantic hashes bind the
Journal hash, line/evidence hashes, policy and Project-company proof hashes,
source classification, recognition mode, and booked amount. Exact redelivery
returns the same pool; semantic drift returns HTTP `409`.

## Installed API

```text
POST /internal/v2/finance/journals/{journal_id}/lines/{journal_line_no}/cost-source-pool
operationId = FINANCE.COST_SOURCE_POOL.ADMIT

GET /internal/v2/finance/cost-source-pools/{pool_id}
operationId = FINANCE.COST_SOURCE_POOL.GET
```

Both routes require an admitted service token for audience `nex-eos`. The
write route accepts only `schema_version`, `source_kind`, and
`allocation_mode`.

Canonical contracts:

```text
contracts/schemas/service/nex_eos/cost_source_pool_admit.v1.schema.json
contracts/schemas/service/nex_eos/cost_source_pool.v1.schema.json
contracts/examples/service/eos_cost_source_pool_admit.v1.json
contracts/examples/service/eos_cost_source_pool.v1.json
```

## Actual PostgreSQL Evidence

The protected smoke connected directly to:

```text
database = nex_eos_test
user     = nex_eos_user
```

It created an isolated schema, applied the complete EOS migration inventory
through `2541`, generated a real immutable Journal through Atomic Posting,
admitted the expense line, replayed the same admission, rejected the cash
asset line, verified exactly one pool row, and dropped the schema with zero
residue.

```text
protected PostgreSQL smoke = 1 passed
```

Remote generation, embedding, and reranking providers were not required.

## Regression And Coverage

Focused regression and changed-source coverage:

```text
tests                                    = 19 passed, 1 protected-smoke skip
cost_source_pools.py statement/branch    = 100% / 100%
cost_source_pool_api.py statement/branch = 100% / 100%
```

Final EOS Slice Gate:

```text
tests               = 1796 passed, 54 protected-smoke skips
statement coverage  = 96.84% (threshold 95.00%)
branch coverage     = 95.11% (threshold 94.00%)
changed files       = 100.00% statement / 100.00% branch
commands            = 6/6 passed
contract validation = PASS (257 schemas, 313 examples, 10 OpenAPI specs)
transition audit    = PASS
dependency audit    = PASS
```

## Entry Decision

```text
S6-01 = PASS / CLOSED
```

S6-02 may now add approved, hash-bound allocation plan revisions. It must use
the SourcePool's exact immutable source identity and must not reinterpret
Project presence, cash movement, or liability settlement as cost eligibility.
