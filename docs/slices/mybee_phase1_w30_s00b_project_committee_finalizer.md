# MyBee Phase 1 W30-S00B Project Committee Finalizer

## Status

- Slice: `W30-S00B`
- Status: implemented and verified
- Design authority: `W30-CA02`
- EOS migration: `2532_eos_project_application_approval.sql`
- Remote model providers: not required

## Boundary

W30-S00B completes the Project application decision path without changing the
S00A application identity or annual code allocator. A SUBMITTED application is
bound to an exact active EOS approval policy whose domain is
`BUSINESS_FORMAL`, transaction type is `PROJECT_APPLICATION`, and sequential
stages use requester exclusion with quorum one.

EOS stores Project-application-specific approval state and an immutable WC
decision ledger. Existing `eos_approval_policy` and policy-stage rows are
reused, while legacy `eos_approval_instance` and accounting scoped approvals
are not overloaded: both require business scope that does not exist before a
Project is approved.

## Runtime

The signed internal contract now provides:

```text
PROJECT.APPLICATION.REQUEST_APPROVAL
```

The request publishes a deterministic WC approval work item. Every delivered
decision is checked against the exact work-item semantic hash, active stage,
fresh OA Human authority, required role, and applicant/approver separation of
duties. Intermediate approval advances exactly one stage and republishes the
next deterministic work item.

Final rejection retains the application as `REJECTED` and creates no Project,
registration code, membership, or PA. Final approval performs the following
in one EOS transaction:

1. append the final immutable decision;
2. allocate the annual registration code;
3. create one `APPROVED_APPLICATION` Project in `ACTIVE` state;
4. create one initial `OWNER` membership for the applicant;
5. bind approval evidence and mark the application `APPROVED`.

The new Project uses `agent_sync_state=PENDING`. EOS lifecycle outbox
publication and AE Project Agent reconciliation remain owned by W30-S00C.
Exact WC replay returns the existing result; changed identity or semantics fail
closed.

## Direct-Create Retirement

Installed EOS dependency composition disables legacy
`PROJECT.PROJECT.CREATE` by default and returns
`EOS_PROJECT_DIRECT_CREATE_RETIRED` with HTTP 410. The constructor keeps an
explicit compatibility switch for controlled historical fixtures and migration
regression only. Canonical deployment profiles do not enable
`NEX_EOS_ALLOW_LEGACY_DIRECT_PROJECT_CREATE`.

## Verification

- Focused S00B unit, API, replay, SoD, rejection, malformed-delivery, and
  recovery tests: `41 passed` with the protected PostgreSQL test disabled.
- Related Project/application/document-signoff regression: `100 passed, 2
  skipped`.
- Actual `nex_eos_test` protected smoke: passed.
  - verified database identity as `nex_eos_test` / `nex_eos_user`;
  - applied all EOS migrations through 2532 in an isolated schema;
  - created and finalized a real PostgreSQL Project committee approval;
  - verified one Project and one immutable decision after exact replay;
  - dropped the isolated schema and verified zero residue;
  - completed the full focused module with `42 passed`.
- NeX-EOS Slice Gate: `1302 passed, 42 skipped`.
  - statement coverage: `96.42%` (threshold `95.00%`);
  - branch coverage: `94.51%` (threshold `94.00%`);
  - contract validation, Golden Journey transition audit, and
    demo-to-product dependency audit: passed.

The W30 entry checkpoint after S00D remains the owner of actual OA/WC/EOS/AE
multi-service acceptance.

## Next Entry

W30-S00C may add the EOS lifecycle outbox and AE Project Agent lifecycle
consumer. It must consume the `agent_sync_state=PENDING` boundary without
recreating Project approval or registration-code semantics.
