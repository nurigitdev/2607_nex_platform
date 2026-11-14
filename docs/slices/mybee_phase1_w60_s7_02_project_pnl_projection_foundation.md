# W60-S7-02 Project P&L Projection Persistence and Classification Foundation

## Decision

`W60-S7-02` establishes a derived, versioned Project P&L projection in
NeX-EOS. The projection is a rebuildable read model and is not a replacement
for immutable PostedJournal, allocation, budget, payroll-evidence, labor-effort,
or material source-of-record data.

The persistence key is tenant, company, project, accounting period, and
projection version. Project UUID remains the internal relational identity;
the approved 11-character Project Code is persisted with every projection and
validated against the EOS Project authority.

## Persistence Boundary

Migration `2543_eos_project_pnl_projection.sql` adds:

- `eos_project_pnl_projection`: immutable projection header, source
  watermarks, reconciliation/freshness state, and commonly queried P&L totals;
- `eos_project_pnl_component`: typed component lines carrying source lineage,
  accounting/work-code context, confidentiality, confirmation state, and a
  deterministic component hash.

Projection revisions are append-only. An exact replay of an existing version
returns the persisted projection; different semantics under the same version
fail closed. A new revision must be the next consecutive version.

## Classification Foundation

The closed classification catalog separates confirmed actuals from outlook
and unresolved amounts:

- confirmed: posted revenue, direct cost, allocated cost, allocated labor,
  realized/unrealized FX, labor adjustment, and material variance;
- unresolved: unallocated expense, payroll residual, and labor overhead;
- non-final: approved-not-posted and provisional labor allocation;
- planning/outlook: budget, forecast, planned labor, BOM forecast, and material
  commitment.

Components additionally carry a provider-neutral source kind and one of
`INTERNAL_FINANCIAL`, `CONFIDENTIAL_FINANCIAL`, or `PAYROLL_SENSITIVE`.
Payroll-sensitive detail is therefore classifiable without placing private
payroll facts in the projection header.

Required posting/allocation watermarks and optional budget, payroll evidence,
labor effort, and material commitment watermarks make projection freshness and
rebuild lineage explicit. Optional watermark reference/timestamp pairs are
atomic and fail closed when incomplete.

## Runtime Integration

`SqlAlchemyEosProjectPnlRepository` is composed by the canonical EOS dependency
factory when a database runtime is configured and is exposed through EOS app
state. This Slice intentionally does not publish a public API or implement the
event-driven projector; deterministic rebuild and projection APIs remain in
the following W60 Slices.

All wire timestamps are normalized to UTC. Actual PostgreSQL replay testing
found that session-local `Asia/Seoul` timestamps otherwise produced a different
wire representation from the initial UTC response for the same instant.

## Verification

Focused unit and branch tests:

```text
tests                  = 42 passed
project_pnl statement  = 99%
project_pnl branch     = 99%
```

Adjacent budget/allocation/source-pool regression:

```text
tests = 163 passed, 1 protected-smoke skip
```

Protected PostgreSQL smoke used the actual `nex_eos_test` database and an
isolated schema. It verified database/user identity, applied the complete EOS
migration inventory through `2543`, seeded authoritative company/project/
account/period data, persisted v1, exact-replayed v1, appended v2, read latest
and version-specific projections, dropped the schema, and confirmed zero
residue.

```text
protected PostgreSQL smoke = 1 passed
```

Final NeX-EOS Slice Gate:

```text
tests               = 2001 passed, 58 protected-smoke skips
statement coverage  = 96.86% (threshold 95.00%)
branch coverage     = 95.07% (threshold 94.00%)
commands            = 5/5 passed
contract validation = PASS (264 schemas, 315 examples, 10 OpenAPI)
transition audit    = PASS
dependency audit    = PASS
```

Remote generation, embedding, and reranking providers were not used.

## Closure

```text
W60-S7-02 Project P&L projection persistence/classification = PASS / CLOSED
```

The next Slice may implement deterministic projection rebuild and watermark
advancement over this foundation. It must continue to treat the projection as
derived data and preserve immutable source lineage.
