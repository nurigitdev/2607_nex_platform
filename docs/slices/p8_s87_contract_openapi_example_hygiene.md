# P8-S87: Contract / OpenAPI / Example Hygiene

## Status

Completed on 2026-10-24.

## Scope

P8-S87 closes the contract hygiene entry gate for P8.9 without changing a
runtime API, database schema, migration, business rule, or service behavior.
It adds a reproducible validator for:

```text
all JSON Schema
all indexed positive and negative examples
all OpenAPI documents
positive/negative index completeness and uniqueness
repository-root and contract-root canonical schema references
AE/WC producer-consumer shared-schema parity
AE/WC/EOS P8 operationId parity
P8 approval/commit canonical terminology
```

Remote providers, PostgreSQL, RustFS, and Playwright are not required for this
contract-only Slice.

## Hygiene Closure

`scripts/quality/validate_p8_contract_hygiene.py` first runs the existing full
contract validator and then applies three additional guard layers:

1. **Reference hygiene** rejects incomplete or duplicate index entries,
   unindexed payloads, missing files, unsafe relative paths, and unresolved
   `x-nex-canonical-json-schema` annotations. References may intentionally be
   rooted in either `contracts/` or the repository, preserving the existing
   P7 canonical handoff schema reference.
2. **Producer/consumer parity** binds the four WC approval schemas exposed by
   both WC and AE and freezes 17 P8 AE/WC/EOS operation paths, methods, and
   operation IDs. Twenty-five parity assertions run in total.
3. **Terminology hygiene** scans all indexed P8 payloads and their 17 canonical
   schemas for forbidden aliases, then verifies the approval-domain and commit
   state enums. Twenty-one terminology assertions run in total.

The reference inventory audit found two valid existing positive examples that
were present on disk but absent from `contracts/examples/index.json`:

```text
ag_operator_review_note.observation.json
ag_redacted_evidence_export.worker_result.json
```

Both are now indexed against their existing canonical schemas. This raises the
positive example inventory from 253 to 255 without introducing a new contract.

## Validation Evidence

```text
ruff                                          = PASS
focused S87 tests                             = 15 passed
focused S87 statement/branch coverage         = 99% / 99%
contract tests                                = 42 passed
P8 regression                                 = 1,789 passed / 63 protected skips
NeX-AE Slice Gate                             = 5,370 passed / 44 protected skips
statement coverage                            = 98.32% / required 95.00%
branch coverage                               = 96.30% / required 94.00%
covered statements                            = 32,565 / 33,121
covered branches                              = 10,503 / 10,906
S87 validator scoped statement coverage       = 99.40%
S87 validator scoped branch coverage          = 98.91%
contract validation                           = 191 schemas / 255 positive
                                                / 221 negative / 9 OpenAPI
reference checks                              = 1,050
producer/consumer and operation parity checks = 25
terminology checks                            = 21
```

The 63 P8 regression skips and 44 Slice Gate skips are pre-existing protected
database, object-storage, browser, admitted-wheel, or live-provider gates.
P8-S87 adds no protected test and no unexpected skip.

The generated coverage report is
`reports/quality/p8-s87-slice.coverage.json`; `reports/` remains intentionally
ignored, so the durable evidence is recorded here.

## Exit Decision

P8-S87 is closed with zero known P0/P1 contract drift. Every contract payload
is indexed, all canonical schema references resolve, shared AE/WC approval
surfaces agree, P8 operation IDs are stable, and canonical approval/commit
terminology is enforced. P8-S88 may now run the full repository regression.
