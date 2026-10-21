# P8-S29 Root Descendant Budget

## Scope

Enforce the initial maximum of 50 delegated descendants below one root
WorkItem, including concurrent admission from different parents.

## Admission Boundary

- descendants exclude the root itself and are counted from immutable
  `wc_delegation_lineage`
- no new relation or migration is introduced
- every nested PostgreSQL admission locks the existing root `wc_work_item`
  row before locking the current parent Claim and Assignment
- the fixed lock order is root WorkItem, parent authority, child/root budget,
  WorkItem and lineage insert
- direct-child and root-descendant budgets are checked in the same transaction
- idempotent replay is resolved before either budget rejects a duplicate request
- a prospective descendant 51 returns
  `wc.delegation_root_budget_exceeded` with zero child residue

The common root lock serializes admissions from different parents without
depending on SQLite concurrency behavior.

## Verification

- focused P8.2A regression: `56 passed`, `2 protected skips`
- actual `nex_wc_test` P8-S29 suite: `4 passed`
- actual cross-parent concurrency started with 49 descendants and produced
  exactly one committed descendant 50 plus one
  `wc.delegation_root_budget_exceeded`
- resulting root count was 50 descendants and 51 total WorkItems
- cleanup proved zero tenant WorkItems after the protected smoke
- WC-related regression with the actual WC test database available:
  `301 passed`, `6 protected skips`
- contract validation: PASS

The generic `nex-wc` Slice Gate command selected only `test_nex_wc_*` and
`test_wc_*`; it omitted existing `test_ae_wc_*` ownership tests and therefore
reported package coverage below its threshold despite the broader WC
regression passing. That gate-profile selection gap is not treated as S29
product evidence. The repository-wide P8-S27 Checkpoint baseline remains
statement `98.71%` and branch `97.17%`; P8-S31 retains the mandatory Full Gate.
