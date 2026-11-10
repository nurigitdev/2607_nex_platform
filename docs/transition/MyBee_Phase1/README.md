# NeX MyBee Phase-1 Design Baseline

This directory is the canonical transition-document set for the NeX-based
MyBee office-work AX Service Phase-1 program.

## Reading Order

1. `NeX_MyBee_D04_D12_Accounting_Transaction_Contract_Closure_v1.0_RC1.md`
2. `NeX_MyBee_D04_D12_EOS_Source_Audit_and_Gap_Analysis_v1.0.md`
3. `NeX_MyBee_D04_D12_Pre_Architecture_Decision_v1.0.md`
4. `NeX_MyBee_D04_D12_EOS_SRS_v1.0.md`
5. `NeX_MyBee_Phase1_InRepo_Deferred_EOS_ADR_v1.0.md`
6. `NeX_MyBee_Phase1_InRepo_Ownership_Override_v1.0.json`
7. `NeX_MyBee_Phase1_CA01_Pre_Implementation_Document_Consistency_Closure_v1.0.md`
8. `NeX_MyBee_Implementation_Slice_Plan_v1.2.md`
9. `NeX_MyBee_Implementation_Slice_Plan_Execution_Matrix_v1.2.json`

The Markdown Slice Plan and its Execution Matrix JSON are one planning set.
The JSON is machine-readable traceability input, not runtime configuration or
evidence that an implementation gate has passed.

### COA Follow-up Reading Order

Read the post-S1-02 standard Chart of Accounts design set in this order:

1. `NeX_MyBee_COA_PAD_v1.0.md` — the base COA design authority.
2. `NeX_MyBee_COA_CA01_v1.0.md` — takes precedence over the COA PAD v1.0
   **only** for the unified GLOBAL/TENANT Codebook structure and its related
   publication/read contracts. All other PAD and SRS invariants remain in
   force.
3. `NeX_MyBee_COA_Codebook_Candidate_v0.1.json` — accounting-review data only;
   it is not an approved operational seed. Its
   `status=DESIGN_CANDIDATE_NOT_APPROVED` and `runtime_seed_allowed=false`
   boundaries must remain fail-closed until exact-row accounting approval.
4. `NeX_MyBee_COA_CA01_Decision_Delta_v1.0.json` — machine-readable evidence
   of the CA01 decision delta, Codex implementation changes, and required
   validation gates. It is not runtime configuration or proof that those gates
   have passed.
5. `NeX_MyBee_COA01_Candidate_Reviewer_Diff_v1.0.md` — COA-01's hash-bound
   88-leaf human review baseline. Structural validation has passed, but the
   original Candidate remains an immutable pre-approval snapshot. Section 4
   records the later COA-01A approval overlay and its exact limitations.

COA-01A machine-readable admission artifacts are read in this order:

1. `domains/mybee/config/account_catalog/product_accounting_approval.v1.json`
2. `domains/mybee/config/account_catalog/approved_standard_chart.v1.json`
3. `domains/mybee/config/account_catalog/approved_seed_manifest.json`

The approval is source admission only. EOS publication, OA publisher
authorization and Company adoption remain separate later gates.

The COA follow-up set preserves the completed S1-02 framework and does not
activate S1-03. It also does not authorize invented K-IFRS account numbers,
candidate seed import, or mutation of existing `eos_account`, company policy,
PostingRule, Golden A, or historical Journal semantics.

## Authority And Status

```text
Frozen NeX Platform v2.1 / Agent v2.1 / admitted NSL contracts
  > EOS canonical business contracts
  > MyBee D04/D12 PAD and SRS
  > Phase-1 in-repository ADR and ownership override
  > CA01 document-consistency closure
  > v1.2 Slice Plan and Execution Matrix
```

Current implementation-entry planning baseline:

```text
NeX repository = nurigitdev/2607_nex_platform
recorded branch = master
recorded commit = 5e64fb1f6b9af2198797d1bcdbc82e577b098fbe
implementation = NOT STARTED by this document set
```

The earlier `c2c03b20e22691cc1984f044e0cacd5d698f9bd3` references are retained
source-audit snapshots. They are historical evidence, not the current coding
entry revision. The implementation entry Slice must refresh repository HEAD,
database migration inventory, dependency revisions, and source hashes before
changing code.

## Canonical Naming

All active Phase-1 artifact filenames use the `NeX_` prefix. In particular,
the canonical SRS filename is:

```text
NeX_MyBee_D04_D12_EOS_SRS_v1.0.md
```

Historical documents may contain the former unprefixed SRS name. Those
references are preserved inside `HISTORY/` as immutable provenance and do not
create a second active SRS.

## History

The following inputs are retained under `HISTORY/` and are not active
implementation instructions:

1. `NeX_MyBee_D04_D12_EOS_Implementation_Slice_Plan_v1.0.md`
2. `NeX_MyBee_D04_D12_EOS_Implementation_Slice_Plan_v1.1.md`
3. `NeX_MyBee_D04_D12_EOS_ISP_v1.1_Repository_Ownership_Matrix.json`

The v1.2 Plan supersedes v1.1 only for repository placement, PR chronology,
and M1/M2 execution gating. Original packet IDs, SRS traceability, and
acceptance obligations remain preserved.

## Open Entry Gates

The following are deliberately not claimed as complete:

- D04/D12 source PDF page-level reconciliation and owner sign-off
- current HEAD and migration-number refresh
- actual PostgreSQL migration, concurrency, and fault acceptance
- public API, Playwright, and end-to-end execution
- accounting, tax, foreign-exchange, and release-owner approval

`Accounting Transaction Contract Closure v1.0-RC1` therefore remains a
conditional closure. A final document may be issued only after its open gates
are satisfied.
