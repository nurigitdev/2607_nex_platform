# P8-S64: Planning Capability Activation

## Status

Completed on 2026-10-23.

## Scope

- Activated the S63 Golden A `FINANCE.CREATE_VOUCHER_DRAFT` admission as one
  exact `LOCAL_SKILL` capability with `WRITE` operation semantics.
- Kept the existing P6 `build_local_skill_capability()` default as `READ` and
  added backward-compatible explicit operation semantics.
- Restricted WRITE activation to the admitted `NSL_V02_IN_PROCESS` backend.
- Added a deterministic Golden A planning boundary that consumes an untrusted
  P6.5 INTENT candidate and binds exact Project, Account, voucher-line policy,
  capability version, executor, and backend from the protected S63 fixture.
- Added a WorkIntent activation step and proved that a provider-suggested
  capability ID binds to the exact version before executable-plan compilation.
- Bound each WorkIntent activation to both the candidate hash and activation
  semantic hash so candidate substitution or activation-payload tampering fails
  closed.
- Hardened the shared INTENT candidate parser against authority-bearing field
  names and parameter names for stable Account references, approval authority,
  idempotency, BusinessOperationId, and EOS commit state.

No database migration, public API field, approval decision, IdempotencyKey,
BusinessOperationId, EOS mutation, or remote-provider call was added.

## Authority Boundary

The live provider may propose:

```text
intent = FINANCE.CREATE_VOUCHER_DRAFT
project search/code candidate
amount/currency/date/type/category/settlement candidates
logical plan with capability_hint
```

The platform alone establishes:

```text
tenant-scoped exact ProjectRef
versioned debit/credit AccountRefs
balanced voucher lines
exact Skill/capability version
LOCAL_SKILL executor
NSL v0.2 backend profile
```

The provider cannot establish Project authority through a stable ID, display
name ranking, first-result selection, or confidence. Display-name and
model-proposed stable-reference matches stop for confirmation. Missing,
mismatched, unknown, or ambiguous business candidates return
`CLARIFICATION_REQUIRED` with no authoritative binding.

Approval authority, idempotency, BusinessOperationId, and commit state remain
outside the activation result and are deferred to the established P8.3-P8.5
governance path.

## Deterministic Binding

The activation reuses the canonical S63 fixture without changing its hash or
activation marker. The exact project code `PROJECT-A-2` resolves to Project
`82000000-0000-4000-8000-000000000001`. The versioned
`golden-a.travel.cash.v1` policy maps the protected `84,000.00 KRW` scenario to:

```text
DEBIT  83000000-0000-4000-8000-000000000001  +84000.00
CREDIT 83000000-0000-4000-8000-000000000002  -84000.00
```

The activated capability is:

```text
capability/skill/tool = FINANCE.CREATE_VOUCHER_DRAFT
exact version         = 1.0.0
executor              = LOCAL_SKILL
operation semantics   = WRITE
backend profile       = NSL_V02_IN_PROCESS
```

Its semantic hash is derived from the immutable fixture hash, exact admission,
backend profile, and voucher-line policy hash. The LLM never supplies that
hash, exact version, executor, or backend.

## PostgreSQL Evidence

The `nex-ae-api` test migration runner connected to the actual local
`nex_ae_test` database as `nex_ae_user`. All tracked migrations were already
current, including `2203_ae_local_skill_activation`.

The protected P8-S64 smoke then:

1. built the schema `1.2` capability snapshot;
2. inserted it into the actual `ae_capability_snapshot` table;
3. reconstructed the repository to model restart;
4. read back the exact WRITE capability and v0.2 backend binding;
5. verified one physical row;
6. deleted the dedicated snapshot row.

Result: `1 passed`, no skip, with zero retained smoke row.

## Verification

- Focused S64 and P6/P6.5 planning regression: passed.
- Protected actual AE PostgreSQL smoke: `1 passed`.
- NeX-AE Slice Gate: `5,115 passed`, `34 skipped` protected tests.
- Service statement coverage: `98.41%` against `95%`.
- Service branch coverage: `96.38%` against `94%`.
- S64 activation statement coverage: `100.00%`.
- S64 activation branch coverage: `100.00%`.
- Contract validation: 188 schemas, 250 positive examples, 217 negative
  examples, and 9 OpenAPI documents.
- Ruff, Black, Python compile, and whitespace checks: passed.

The first scoped Slice Gate correctly exposed insufficient defensive-branch
coverage. Additional corruption, ambiguity, authority-forgery, invalid-value,
and candidate-shape tests raised scoped branch coverage above the gate before
the final successful run.

## Exit Decision

P8-S64 is closed. Golden A planning can now accept a live P6.5 provider's
candidate intent and plan while keeping every business and execution authority
binding deterministic and fail-closed. P8-S65 may connect the actual prompt,
plan, LOCAL_SKILL, NSL prefix, Approval Inbox, human decision, and resume path.
That next Slice is where the remote generation provider and the cross-service
AE/WC/OA PostgreSQL journey become required.
