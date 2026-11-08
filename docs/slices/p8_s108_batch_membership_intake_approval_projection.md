# P8-S108: Batch Membership Intake and Approval Projection

## Scope

P8-S108 adds the AE protected admission boundary between the P8-S107 OA
employee batch resolver and the future collection-valued NSL controlled WRITE.

- AE calls the protected OA batch endpoint through a bounded, service-token
  authenticated HTTP client.
- Only OA `RESOLVED` items can enter the admitted member set.
- Subjects are deduplicated by `(tenant_id, subject_id)` and sorted by
  `subject_id` UTF-8 byte order.
- Subject and tenant-membership revisions remain protected admission lineage;
  the OA evidence hash binds those revisions to the governed payload.
- An empty admitted set returns `REJECTED` and contains no governed payload,
  payload hash, or approval projection.
- No database table, migration, or public API is added.

Existing `PROJECT.MEMBERSHIP.ADD` planning and artifact admission remain
unchanged. `PROJECT.MEMBERSHIP.ADD_MANY` NSL capability activation belongs to
P8-S110 after the EOS mutation boundary is complete.

## Canonicalization

The raw intake is structurally bounded to 50 candidates and is represented in
protected lineage by `protected_intake_hash`. OA remains the only owner of
employee-number normalization, identity resolution, subject status, and
tenant-membership eligibility.

The controlled payload contains only:

```text
tenant_id
requester_subject_id
project_id
target_subject_ids
member_role
resolution_evidence_hash
```

`member_role` defaults to `MEMBER` and is common to the complete batch. The
exact payload receives the shared NSL-compatible payload hash. The approval
projection binds the Project, canonical target set, common role, rejection
count, OA evidence hash, and payload hash. Any changed subject, order,
Project, role, evidence, or approval summary fails closed.

OA dependency failures and unverifiable response/evidence states remain
retryable operation failures. They are never converted into partial business
success. Item-level OA rejection and AE same-subject deduplication remain safe
user-result projections without subject-authority leakage.

## Contracts

P8-S108 adds canonical schemas and fixtures for:

- Project membership batch intake;
- canonical batch admission and approval projection;
- model-supplied subject authority rejection;
- all-rejected admission carrying write authority rejection.

Contract validation passed with `203` schemas, `267` positive examples, `229`
negative examples, and `9` OpenAPI documents.

## Verification

- focused unit, adversarial, HTTP-client, evidence, and approval tests:
  `71 passed`
- focused module statement coverage: `100.00%`
- focused module branch coverage: `100.00%`
- AE Slice Gate: `5480 passed`, `44` expected protected-smoke skips
- AE aggregate statement coverage: `98.35%`
- AE aggregate branch coverage: `96.36%`
- Slice Gate commands: `4/4`, `351.801` seconds
- Ruff, contract validation, and `git diff --check`: passed

The Slice Gate coverage report is
`reports/quality/p8-s108-ae.coverage.json`.

## Exit

P8-S108 is complete. P8-S109 may reuse the exact governed payload shape to
implement one EOS BusinessOperation and one transaction for partial
item-outcome `PROJECT.MEMBERSHIP.ADD_MANY` execution. Actual OA/AE PostgreSQL
integration remains scheduled for P8-S112.
