# P8-S97: Canonical Operation Alias Registry

## Status

Completed on 2026-10-25.

## Scope

P8-S97 added the shared, immutable operation-name registry used at governed
service boundaries. Canonical identities have exactly three segments:

```text
<DOMAIN>.<BUSINESS_OBJECT>.<ACTION>
```

The registry admits the P8 Project, membership, and Voucher draft operations.
Legacy names remain accepted only through explicit versioned aliases. Unknown,
lower-case, two-segment, cyclic, and invalid-target aliases fail closed.

## Boundary Rules

Alias resolution happens once, before payload hashing and idempotency
admission. The canonical identity is then used for the payload hash, route
operation, BusinessOperation lineage, OpenAPI operation ID, and subsequent
authorization or audit processing.

The original requested identity is retained as diagnostic lineage. It is not
part of the canonical business payload and therefore cannot split idempotency
between a legacy alias and its canonical replacement. A valid alias targeting
a different route operation is rejected.

The initial compatibility aliases are:

```text
FINANCE.CREATE_VOUCHER_DRAFT         -> FINANCE.VOUCHER_DRAFT.CREATE
FINANCE.GET_VOUCHER_DRAFT            -> FINANCE.VOUCHER_DRAFT.GET
FINANCE.RESOLVE_VOUCHER_DRAFT_COMMAND -> FINANCE.VOUCHER_DRAFT.RESOLVE_COMMAND
PROJECT.GET_PROJECT                  -> PROJECT.PROJECT.GET
```

## Contracts

`canonical_operation_alias.v1` records requested identity, canonical identity,
registry version, and whether an alias was applied. Its positive and negative
examples are registered in the repository contract indices. All seven EOS
Project API operations now expose canonical OpenAPI operation IDs.

## Verification

Focused regression and coverage:

```text
31 passed
1 expected protected skip
operation registry coverage = 97%
Project API coverage         = 100%
Project service coverage     = 97%
combined focused coverage    = 98%
```

Contract validation:

```text
schemas           = 192
positive examples = 256
negative examples = 222
OpenAPI documents = 9
references        = 1054
parity checks     = 25
terminology checks = 21
result            = PASS
```

Actual `nex_eos_test` PostgreSQL governed Project smoke remained executable
after the canonical lineage change and passed without skip.

P8-S97 Checkpoint Gate:

```text
commands                    = 3 / 3
duration                    = 716.399 seconds
statement coverage          = 98.67%
branch coverage             = 97.15%
canonical threshold         = 96% / 94%
result                      = PASS
```

## Exit Decision

P8-S97 is closed. Canonical operation identity is now stable before hash,
idempotency, OpenAPI, and audit use. P8-S98 may add canonical Project NSL READ
Skills and Tools without introducing another naming source.
