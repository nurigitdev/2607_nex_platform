# GB2-CA00-S10: Productize Golden A Finance Activator

## Scope

S10 promotes Golden A semantic activation from a P8 Demo fixture adapter to a
registered finance product profile. It adds no database migration, public API,
remote-provider dependency, or worker state-machine change.

## Product Boundary

The canonical registration preserves the distinct identities:

```text
Capability = FINANCE.CREATE_VOUCHER_DRAFT
Skill      = FINANCE.VOUCHER_DRAFT_CREATE
```

`GoldenAFinanceAuthoritySource` is the product authority port. Its first
implementation admits a hash-protected, tenant-scoped versioned profile from
`deployment/environments/finance-golden-a-vo00.v1.json`. The source verifies
tenant, requester, Project, Account, voucher policy, Skill, backend profile,
and protected business input before deterministic binding.

The profile source is intentionally replaceable by EOS/OA repository-backed
authority in a later Slice. Semantic admission depends only on the canonical
registry and passes the request tenant to the activator; it neither imports nor
parses Demo fixtures.

## Compatibility Boundary

`p8_demo_semantic_activation.py` and the packaged Demo fixtures remain only for
historical compatibility and the existing controlled-WRITE worker composition.
The AE API product registry does not read:

```text
NEX_AE_DEMO_FIXTURE
NEX_AE_DEMO_BASE_FIXTURE
scripts/smoke/data/*
scripts/deployment/data/*
```

The P8 Demo image now packages the canonical finance profile separately and
the Compose API process points semantic admission to that product source.

## Fail-Closed Rules

```text
profile hash mismatch       -> reject
tenant mismatch             -> reject
requester mismatch          -> reject
unknown/ambiguous Project   -> clarification or reject
missing policy Account      -> reject
Capability/Skill drift      -> reject
```

The trusted context manifest records `FINANCE_AUTHORITY_PROFILE`; it no longer
claims a fixture as the product authority source. Replay with the same profile,
candidate, WorkIntent, requester, and timestamp is deterministic.

## Verification

```text
focused product/compatibility regression = 83 passed
database migration                       = NONE
PostgreSQL / remote provider              = NOT REQUIRED
AE Slice Gate                             = 5,670 passed / 45 skipped
AE statement / branch                     = 97.00% / 95.28%
Checkpoint Gate #2                        = 17,717 passed / 131 skipped
Checkpoint statement / branch             = 98.22% / 96.67%
contract validation                       = 226 / 290 / 244 / 10
ruff / diff check                         = PASS
```

## Exit

```text
Golden A product activator        = READY
tenant-scoped authority source    = FAIL-CLOSED
Capability/Skill separation       = PRESERVED
generic Demo fixture dependency   = REMOVED
historical Demo worker boundary   = PRESERVED
next slice                        = GB2-CA00-S11
```
