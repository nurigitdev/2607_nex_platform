# MyBee Phase-1 COA-02: Unified COA Persistence Foundation

## Scope

COA-02 adds the additive NeX-EOS persistence foundation for the approved
MyBee unified chart of accounts. It does not replace the existing tenant GL
`eos_account` source of record and does not publish or adopt a chart.

The migration introduces five deliberately short table names:

- `eos_coa_definition_release`
- `eos_coa_entry`
- `eos_coa_code_identity`
- `eos_coa_company_adoption`
- `eos_coa_account_binding`

`GLOBAL` definitions have no synthetic tenant owner. `TENANT` extensions
require a real tenant owner and an immutable published GLOBAL base. Standard
leaf suffixes use `001..699`; tenant extension leaves use `800..999`.

## Implementation

- migration `2518_eos_unified_coa` creates the release, entry, stable identity,
  company adoption, and GL binding records;
- PostgreSQL triggers enforce release/entry scope alignment, governed
  hierarchy, normal balance, postability, namespace ownership, adoption
  overlap, binding scope, and published-entry immutability;
- `SqlAlchemyEosUnifiedCoaRepository` persists DRAFT releases atomically and
  supports exact idempotent replay and deterministic read ordering;
- malformed input, semantic replay drift, database identity conflicts, and
  persistence failures are fail-closed with redacted domain errors;
- the existing account catalog, posting rules, company policy, and
  `eos_account` runtime paths remain unchanged.

Publication, stable identity ledger activation, company adoption, and OA
authorization remain COA-03 responsibilities.

## PostgreSQL Evidence

The protected smoke connected to the actual `nex_eos_test` database as
`nex_eos_user`. It created an isolated schema, applied the complete NeX-EOS
migration inventory through `2518`, persisted a four-level GLOBAL DRAFT, and
proved that scope drift and invalid parent-code updates are rejected by the
database. The isolated schema was dropped afterward, leaving zero test
residue.

## Verification

```text
focused COA-02 tests: 31 passed, 1 protected skip
actual nex_eos_test PostgreSQL smoke: 1 passed
nex-eos Slice Gate: 870 passed, 25 explicit protected skips
Slice Gate statement coverage: 95.93% (threshold 95.00%)
Slice Gate branch coverage: 94.49% (threshold 94.00%)
unified_coa.py statement coverage: 98.44%
unified_coa.py branch coverage: 95.00%
contract validation: PASS (233 schemas / 292 examples / 245 negatives / 10 OpenAPI)
Golden Journey transition audit: PASS
product dependency audit: PASS
remote provider requirement: NONE
```
