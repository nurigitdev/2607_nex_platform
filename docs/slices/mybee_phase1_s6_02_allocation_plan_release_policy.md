# MyBee Phase 1 S6-02 Allocation Plan Release and Policy

## Status

```text
Slice = S6-02
Decision = PASS / CLOSED
Date = 2026-11-13
Owner = NeX-EOS
Remote provider required = NO
Database migration = NO
```

## Objective

S6-02 establishes the immutable allocation-plan release boundary consumed by
the W50 allocation flow. A plan revision is admitted only after an exact final
`BUSINESS_FORMAL` approval proof and a fresh OA authorization check for the
human approver. The released plan preserves Project, WorkCode, basis, rule,
and approval lineage without allocating or posting any amount.

This Slice deliberately does not implement allocation execution. SourcePool
consumption, amount calculation, rounding, residual handling, and journal
posting remain later W50 responsibilities.

## Source And Structure Audit

The pre-existing migration
`2541_eos_cost_source_allocation.sql` already defines the canonical
`eos_cost_allocation_plan` and `eos_cost_allocation_plan_line` structures.
S6-02 therefore reuses that schema and adds no migration or table.

The implementation follows existing EOS ownership boundaries:

- `allocation_plans.py` owns admission, exact approval binding, fresh OA
  authorization, immutable revision persistence, Project/company validation,
  and read projection.
- `allocation_plan_api.py` owns signed service-token HTTP admission and problem
  responses.
- `dependencies.py` composes the service only when PostgreSQL and OA
  authorization dependencies are available.
- `app.py` exposes the routes without introducing a second approval or job
  subsystem.

## Canonical Policy

### Release admission

A release requires all of the following:

1. canonical `eos_cost_allocation_plan_release.v1` input;
2. a final EOS `BUSINESS_FORMAL` proof;
3. proof, instance, operation, policy, and final WC decision consistency;
4. exact binding to `plan_id`, `plan_revision`, and `plan_hash`;
5. final decision `APPROVE` with `authorized_by_oa=true`;
6. fresh OA authority for the final approver with
   `finance:cost-allocation-plan:approve`;
7. an ACTIVE LegalEntity for the effective period;
8. ACTIVE or CLOSING target Projects with exact approved Project codes;
9. an effective APPROVED ProjectCompanyBinding for every target Project;
10. allocation ratios totaling exactly one.

An exact replay returns the existing revision. Different semantics for the
same identity, a skipped revision, stale authority, malformed evidence, or a
scope mismatch fail closed with zero mutation.

### Basis priority

```text
priority 1 = ACTUAL_WORK or USAGE
priority 2 = APPROVED_PLAN
priority 3 = HEADCOUNT_CASCADE
priority 4 = JUSTIFIED_PERCENTAGE
```

`APPROVED_PLAN` additionally requires an effective WorkAssignment for every
line, an FL WorkCode, exact planned man-day units, and the exact aggregate
assignment hash. The other basis types preserve their source reference and
hash for later execution adapters; S6-02 does not reinterpret those sources.

### Immutability

The product API exposes only release and exact read operations. It exposes no
update or delete command. Revisions are sequential and append-only through the
EOS repository, and an existing identity can only be returned by exact replay.
The existing migration remains unchanged.

## API And Contract

```text
POST /internal/v2/finance/cost-allocation-plans/releases
  operation = FINANCE.COST_ALLOCATION_PLAN.RELEASE

GET /internal/v2/finance/cost-allocation-plans/{plan_id}/revisions/{revision}
  operation = FINANCE.COST_ALLOCATION_PLAN.GET
```

Both routes require a valid signed service token. Release additionally
requires the fresh human OA authority described above.

Added schemas:

- `cost_allocation_plan_release.v1.schema.json`
- `cost_allocation_plan.v1.schema.json`

Repository contract validation result:

```text
schemas          = 259
examples         = 313
negative examples= 257
OpenAPI specs    = 10
result           = PASS
```

## PostgreSQL Protected Smoke

The protected smoke connected directly to:

```text
nex_eos_test as nex_eos_user
nex_wc_test  as nex_wc_user
nex_oa_test  as nex_oa_user
```

It performed the following real sequence:

1. brought EOS, WC, and OA migrations to the current inventory;
2. created an OA membership with approval and allocation-plan scopes;
3. created EOS LegalEntity, Project, company binding, organization, and
   approver position data;
4. created a one-stage EOS approval policy and exact approval instance;
5. projected the stage to the actual WC repository;
6. recorded an OA-authorized WC approval decision;
7. advanced EOS to a final `BUSINESS_FORMAL` ApprovalProof;
8. released the allocation plan and verified exact replay;
9. removed the OA membership and verified a subsequent replay was denied with
   HTTP semantics `403`, not treated as a retryable dependency outage;
10. verified one immutable plan revision and tenant-scoped zero residue after
    cleanup.

```text
protected PostgreSQL smoke = 1 passed
```

Remote generation, embedding, and reranking providers were not used.

## Regression And Coverage

Focused implementation tests:

```text
tests                               = 52 passed
allocation_plans.py statement       = 96.38%
allocation_plans.py branch          = 99.07%
allocation_plan_api.py statement    = 100.00%
allocation_plan_api.py branch       = 100.00%
```

Adjacent W40/W50 regression:

```text
tests = 190 passed, 2 protected-smoke skips
```

Final EOS Slice Gate:

```text
tests               = 1848 passed, 55 protected-smoke skips
statement coverage  = 96.84% (threshold 95.00%)
branch coverage     = 95.23% (threshold 94.00%)
commands            = 6/6 passed
contract validation = PASS
transition audit    = PASS
dependency audit    = PASS
```

## Entry Decision

```text
S6-02 = PASS / CLOSED
```

The next W50 Slice may consume an approved immutable plan revision, but it
must preserve the exact SourcePool, plan, basis, Project, WorkCode, and proof
lineage established by S6-01 and S6-02.
