# P8-S71: BUSINESS_FORMAL WC Adapter

## Status

Completed on 2026-10-23.

## Scope

NeX-EOS can now project the single active P8-S70 ApprovalStage into the
existing WC ApprovalWorkItem boundary with:

```text
approval_domain = BUSINESS_FORMAL
approval_provider_type = EOS
source_ref = EOS ApprovalStage stable ref
approval_target_ref = EOS ApprovalStage stable ref
resume_target_ref = EOS ApprovalInstance/stage transition target
```

This Slice adds:

- `EosBusinessFormalWcAdapter` for active-stage projection;
- a thin `HttpWcApprovalWorkItemClient` using WC's existing protected
  `POST /api/v1/approval-work-items` create-or-get API;
- deterministic WC work-item identity derived from tenant and EOS stage ID;
- fail-closed WC response-lineage validation;
- optional EOS runtime wiring controlled by `NEX_EOS_TO_WC_SERVICE_TOKEN` and
  `NEX_WC_BASE_URL`.

No database migration or new WC table was required. The existing
`wc_approval_work_item` aggregate remains the human-task SoR.

## Projection Binding

Only a `PENDING` `BUSINESS_FORMAL` ApprovalInstance with an exactly matching
`ACTIVE` stage can be projected. The WC semantic hash binds:

```text
ApprovalInstanceId + ApprovalStageId + stage order/profile
+ exact policy ID/version/hash
+ BusinessOperationId + operation
+ protected operation ref + PayloadHash + WriteIntentHash
+ requester + OrgUnit + Project
+ role/org/project decision targets
```

The display-safe summary contains only the operation, stage position/order,
and stable OrgUnit/Project IDs. It does not publish protected payload content.
Expired instances, missing or mismatched stages, terminal instances, malformed
WC responses, and WC lineage drift all fail closed.

## Idempotency And Ownership

The work-item ID is UUIDv5-derived from tenant and ApprovalStage ID. WC's
existing unique `(tenant_id, approval_domain, source_ref)` boundary therefore
converges process restart and network retry onto the original work item.

WC owns:

- human inbox and task state;
- OA-authorized human decision capture;
- decision outbox event.

EOS continues to own ApprovalInstance and ApprovalStage state. S71 performs no
EOS stage mutation. P8-S73 will validate a WC decision and atomically append the
EOS decision plus stage/instance transition.

P8-S72 remains responsible for leadership-ladder and concrete approver
resolution. S71 preserves the stage's position type and OrgUnit/Project scope
without inventing a person-level approver.

## Verification

- Focused S70/S71 regression: `58 passed`, `1 protected skip`.
- Existing WC approval contract/create-or-get/publication regression plus S71:
  `49 passed`, `1 protected skip`.
- Actual PostgreSQL test migrations confirmed current for both `nex_eos_test`
  and `nex_wc_test`.
- Actual dual-PostgreSQL protected smoke: `1 passed`, no skip.
- Protected smoke verified both database/role identities, EOS instance and
  stage persistence, WC work-item creation, restart-style replay, source
  readback, tenant isolation, and zero residue in both databases.
- NeX-EOS Slice Gate: `507 passed`, `16 protected skips`.
- EOS Slice Gate statement coverage: `99.58%`.
- EOS Slice Gate branch coverage: `99.63%`.
- New adapter statement and branch coverage: `100% / 100%`.
- Contract validation: `188` schemas, `250` examples, `217` negative examples,
  and `9` OpenAPI documents.
- Ruff and Black checks: passed.

Remote embedding, reranking, and generation providers were not required.

## Exit Decision

P8-S71 is closed. P8-S72 can resolve one-, two-, and multi-stage leadership
ladders into authoritative EOS position assignments while retaining the WC
projection and ownership boundary established here.
