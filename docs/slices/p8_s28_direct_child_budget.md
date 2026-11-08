# P8-S28 Direct Child Budget

## Scope

Enforce the initial maximum of five direct delegated children per parent
WorkItem, including concurrent PostgreSQL admission.

## Concurrency Boundary

- the current parent Claim and Assignment are locked before budget evaluation
- every child of the same parent serializes on that parent authority row
- the direct child count comes from immutable `wc_delegation_lineage`
- idempotent replay returns the existing child without consuming budget
- a prospective sixth child returns `wc.delegation_child_budget_exceeded`
- denial creates zero WorkItem and zero lineage

## Verification

- focused P8.2A regression with live PostgreSQL: `55 passed`
- actual `nex_wc_test` six-way concurrency smoke: PASS; exactly `5`
  children committed and `1` returned
  `wc.delegation_child_budget_exceeded`
- WC migrations applied through `1005_wc_assignment_execution`
- P7/WC compatibility regression with available PostgreSQL tests:
  `332 passed`, `5 protected skips`
- smoke cleanup proved zero tenant WorkItems after execution

The P8-S27 Checkpoint baseline remains statement `98.71%` and branch `97.17%`.
The next repository-wide Full Gate remains scheduled for P8-S31.
