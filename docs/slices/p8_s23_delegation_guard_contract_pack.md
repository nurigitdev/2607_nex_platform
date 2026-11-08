# P8-S23 Delegation Guard Contract Pack

## Scope

Freeze the machine-readable entry contracts for the P8.2A WC Delegation Guard
without changing the P7 WorkItem runtime or persistence boundary.

## Decisions

- The initial governance-controlled policy is depth `10`, direct children `5`,
  root descendants `50`, and cycle detection enabled.
- Policy values are explicitly not LLM-overridable.
- Existing P7 `DelegationSpec` version `1.0` remains unchanged and valid.
- Nested delegation uses the additive `DelegationSpec` version `1.1` contract.
- Parent WorkItem, Claim, Claim generation, and delegating Agent fields are an
  all-or-none authority group.
- Delegation lineage carries an immutable policy reference and semantic hash.
- First-level lineage has depth `1` and no parent Claim authority.

## Contract Inventory

- `DelegationPolicy`
- `DelegationLineage`
- nested `DelegationSpec 1.1`
- three positive examples and three fail-closed negative examples

## Verification

- focused contract tests: `9 passed`
- P7/WC compatibility regression: `274 passed, 8 protected skips`
- canonical contract validation: `179` schemas, `241` examples, `210`
  negative examples, and `9` OpenAPI documents
- whitespace validation: pass

The generic `nex-wc` Slice Gate profile collected only `test_nex_wc_*` and
reported statement `63.11%` and branch `47.09%` because substantial WC coverage
is owned by the cross-service `test_ae_wc_*` P7 suites. This Slice changes no
runtime source, so source coverage is not applicable here. The broader P7/WC
regression above was run explicitly, and repository-wide coverage remains a
required P8-S27 Checkpoint Gate.
