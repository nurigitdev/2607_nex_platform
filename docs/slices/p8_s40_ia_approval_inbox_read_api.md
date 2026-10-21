# P8-S40 IA Approval Inbox Read API

## Ownership And Authorization

WC remains the ApprovalWorkItem system of record. IA and AE-WEB receive only a
presentation projection through the WC API; they do not persist authoritative
approval state.

Every inbox read performs a current OA effective-authorization lookup for the
requested tenant and subject. The request is admitted only when:

```text
active == true
approval:read is present
tenant_id and subject_id match the OA response
```

Typed OA denial maps to `403`; OA or WC dependency failure maps to retryable
`503`.

## Eligibility And Bounds

WC reads only tenant-scoped `PENDING` ApprovalWorkItems, excludes expired
items, and applies the same exact principal or role/org/project target matching
used by the decision boundary.

```text
response limit: 1..100
candidate scan limit: 1000
ordering: created_at, approval_work_item_id
```

`scan_truncated` makes the bounded scan visible to callers instead of implying
an unbounded complete result.

## Safe Projection

The API returns `wc_approval_inbox.v1` with domain-preserving
`human_gate_view.p8.v1` entries. The list includes only display-safe title and
summary, provider/domain, controlled `action_ref`, opaque approval target,
business operation reference, and expiry.

The projection excludes:

```text
protected_request_ref and payload
semantic_hash
source_ref
resume_target_ref
agent/step/NSL execution internals
```

Protected endpoint:

```text
GET /api/v1/approval-gates
X-NeX-Tenant-Id: <tenant>
X-NeX-Subject-Id: <OA user>
service scope: service:call
user scope checked by WC: approval:read
```

## Verification

- focused S40 tests: `16 passed`
- cumulative approval tests: `119 passed`
- cumulative approval coverage: `98.09% statement`, `95.51% branch`
- WC/AE integration regression: `421 passed`, `12 protected skips`
- contract validation: `186 schemas`, `248 examples`, `216 negative`,
  `9 OpenAPI` passed
- Ruff checks: passed
- historical S32 contract inventory assertion now verifies its four owned
  canonical entries instead of freezing the total WC contract count
