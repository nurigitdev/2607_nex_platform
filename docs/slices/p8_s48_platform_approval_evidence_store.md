# P8-S48 Platform Approval Evidence Store

## Scope

P8-S48 establishes AE as the source of record for the canonical immutable
Platform ApprovalEvidence required by the frozen P8 contract. The Slice joins
already-authoritative snapshots from:

- the protected NSL `ApprovalRequest` stored by AE;
- the exact AE `NSL_APPROVAL` wait registration;
- the terminal WC `ApprovalWorkItem` and immutable `ApprovalDecision`;
- the metadata-safe OA authority reference preserved by WC.

It does not project the record into the NSL public `ApprovalEvidence`; that is
P8-S49 scope. It also does not add direct AE database access to WC or OA.

## Persistence

Migration `2504_ae_approval_evidence` creates the concise AE-owned
`ae_approval_evidence` table. Its primary identity is
`(tenant_id, approval_request_id)`, and each WC ApprovalWorkItem may bind at
most one evidence row per tenant.

The record contains the complete frozen Platform field set:

```text
tenant_id
agent_execution_id
executable_step_id
nsl_execution_id
business_operation_id
approval_id
approval_request_id
skill_semantic_hash
decision
approver_id
decided_at
expires_at
payload_hash
write_intent_hash
approval_work_item_ref
oa_decision_ref
protected_request_ref
evidence_integrity
```

`created_at` is storage metadata. PostgreSQL foreign keys bind the record to
the AE execution, step, and protected request sources of record. Cross-service
WC/OA foreign keys are intentionally not introduced.

## Integrity And Admission

`evidence_integrity` uses the shared
`nex_runtime.semantic_hashes.semantic_sha256_hash_ref()` implementation over
the canonical immutable field set, excluding the integrity field itself.

Evidence construction fails closed unless all of the following are true:

- tenant, execution, step, NSL execution, business operation, and request
  identities agree across all snapshots;
- the wait is an active, non-cancelled `NSL_APPROVAL` checkpoint with a
  positive checkpoint version;
- the WC item is `NSL_WRITE`, binds the protected request hash/reference, and
  is in the terminal state matching the decision;
- the decision is OA-authorized and preserves a valid OA decision reference,
  authority revision hash, and authorization check timestamp;
- request and work-item expiration agree, and the decision precedes expiry.

Storage is append-once. An identical retry returns the existing row; reuse of
the request identity or work-item reference with different semantics is an
idempotency conflict. Loaded rows are revalidated, so persisted tampering is
detected before use.

## Verification

- focused S44A-S48 approval regression: `110 passed`, `2 protected skips`
- focused S48 tests: `37 passed`
- actual `nex_ae_test` migration:
  - `2504_ae_approval_evidence` applied successfully
- actual `nex_ae_test` + `nex_wc_test` protected smoke: `1 passed`
  - protected request and exact wait persisted in AE
  - WC ApprovalWorkItem created and OA-authorized terminal decision committed
  - Platform ApprovalEvidence built from records selected from both databases
  - identical double write produced exactly one AE evidence row
  - all scoped smoke rows were deleted after verification
- AE Slice Gate: PASS
  - Python: `4714 passed`, `22 protected skips`
  - statement coverage: `98.34%`
  - branch coverage: `96.23%`
  - new module statement/branch coverage: `99.51% / 98.08%`
- contracts: `188` schemas, `250` examples, `217` negative examples,
  `9` OpenAPI documents
- remote providers: not required

The first Slice Gate run exposed a new-file branch score below the scoped
threshold. Additional fail-closed tests covered expiration, malformed time,
NSL object input, unique-reference conflict, and persisted-integrity tamper;
the threshold was not reduced.

## Handoff

P8-S49 may project this canonical AE record to the admitted NSL v0.2
`ApprovalEvidence` API and verify its provenance without allowing Platform
fields to override the original NSL binding hashes. The mandatory post-S48
Checkpoint Gate follows this Slice commit.
