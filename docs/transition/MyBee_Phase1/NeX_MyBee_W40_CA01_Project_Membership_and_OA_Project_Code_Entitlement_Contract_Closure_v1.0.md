# NeX MyBee W40-CA01: Project Membership and OA Project-Code Entitlement Contract Closure v1.0

## 1. Status And Authority

- Decision date: `2026-11-12`
- Status: `DESIGN_CLOSED_IMPLEMENTATION_REQUIRED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `0d0cbb981b4ea4968f348a99798039d9eddbb792`
- Runtime code changes by this document: none

This controlled amendment is the mandatory authorization entry contract before
W40 `S4-01`. It supplements W30-CA02 without rewriting its Project application,
business-code, lifecycle, Project Agent, or accounting-attribution decisions.

This amendment takes precedence only for:

- separation of the Project applicant, accountable owner, Project Manager
  (`PM`), and initial Project members;
- EOS ownership of Project membership business state;
- OA ownership of Project authorization decisions through a derived entitlement
  projection;
- Project registration code as the human-facing and authorization-facing
  resource identifier;
- approval, membership, lifecycle, replay, revocation, and reconciliation
  behavior between EOS and OA; and
- fail-closed Project authorization required by W40 accounting admission.

All existing WC `BUSINESS_FORMAL`, OA Human authority, accounting SoD, Project
UUID FK, proof-domain separation, Project Agent, and mandatory Project
attribution rules remain in force unless this document explicitly narrows or
strengthens them.

## 2. Source-Backed Current State And Gaps

| Boundary | Confirmed current behavior | Required closure |
| --- | --- | --- |
| Project application | `ProjectApplicationDraft` contains `applicant_subject_id`, but no accountable owner, PM, or initial-member set | introduce explicit parties and immutable submitted membership intent |
| Final approval | EOS creates an ACTIVE Project and grants the applicant `OWNER` | materialize the admitted owner, PM, and initial members; do not grant the applicant implicitly |
| Project membership SoR | `eos_project_member` owns `OWNER/MANAGER/MEMBER/VIEWER` membership and lifecycle | retain EOS as business membership SoR |
| OA authorization | OA resolves tenant roles, scopes, and groups; it does not persist or return Project entitlement | add an OA Project entitlement projection and decision contract |
| Cross-service event | Project lifecycle outbox is currently consumed for AE Project Agent synchronization | add a distinct EOS-to-OA authorization synchronization boundary |
| Project-scoped checks | some EOS paths check `eos_project_member`; other paths inspect optional `project_ids` from authorization responses | replace optional behavior with explicit Project-Code admission and fail closed |
| Resource identity | EOS UUID is the technical PK; approved Project code is immutable and tenant-unique | keep UUID for internal lineage and use `(tenant_id, project_code)` at the authorization boundary |

The existing `manager_subject_id` parameter used by membership mutation code
means the authorized actor performing the mutation. It is not the canonical PM
identity and must not be reused or presented as such.

## 3. Ownership And Decision Boundary

### W40-CA01-ADR-01: EOS Owns Membership; OA Owns Authorization Decisions

The following ownership split is normative:

| Concern | Authoritative owner | Notes |
| --- | --- | --- |
| Project identity, application, code, lifecycle | EOS | existing W30-CA02 boundary |
| Project applicant, accountable owner, PM, member role and membership status | EOS | canonical business state and history |
| Human identity, tenant membership, account activity | OA | fresh identity authority |
| Project resource entitlement used to allow or deny an action | OA | derived, versioned projection from EOS |
| Project Agent identity and runtime status | AE | synchronized from EOS lifecycle |

OA MUST NOT become a second manually editable Project-member master. EOS emits
authoritative membership and lifecycle facts; OA applies them idempotently and
uses the resulting projection for authorization decisions.

EOS MUST NOT call OA and then treat a missing Project resource field as
unrestricted access. A Project-protected action is admitted only when OA returns
an explicit, current allow decision for the exact tenant, subject, Project code,
and action.

This projection avoids a synchronous OA-to-EOS dependency during every access
decision while preserving OA as the authorization SoR. Delivery lag is handled
by fail-closed readiness, replay, and reconciliation rather than optimistic
authorization.

## 4. Project Party And Initial Membership Contract

### W40-CA01-ADR-02: Applicant, Owner, And PM Are Independent Roles

The following identities are distinct concepts even when the same person fills
more than one role:

| Field | Meaning | Automatic Project access |
| --- | --- | --- |
| `applicant_subject_id` | creates and submits the application | none |
| `project_owner_subject_id` | accountable Project owner/sponsor | `OWNER` |
| `project_manager_subject_id` | operating Project Manager (`PM`) | `MANAGER`, unless the same subject is the owner |
| `initial_members[]` | admitted initial Project team | explicit role only |

Rules:

1. Applicant, owner, and PM MAY be the same person or different people.
2. Owner and PM are required before submission. No implicit fallback from
   applicant to either role is allowed.
3. The applicant receives Project access only when explicitly admitted as the
   owner, PM, or an initial member.
4. The owner is normalized to one active `OWNER` membership.
5. When PM differs from owner, PM is normalized to one active `MANAGER`
   membership.
6. When owner and PM are the same subject, EOS stores one `OWNER` membership;
   the application/Project PM binding preserves the PM designation and `OWNER`
   includes Project-management capability.
7. An initial-member entry for the owner or PM must agree with the normalized
   role. Conflicting duplicates fail closed.
8. Every subject must be an active member of the same OA tenant at submission
   and must be checked again at final approval.
9. Names and employee numbers are selection/display attributes only. OA
   `subject_id` is the durable person identity.

The DRAFT may be edited and versioned. Submission freezes one immutable
application revision containing the exact owner, PM, and normalized initial
membership set. Final approval materializes exactly that revision. A changed
set requires return to an admitted editable state or a new application; it
cannot be substituted during finalization.

The Project record or an equivalent immutable initial-party binding must retain
the approved owner and PM identity. Later owner or PM changes require a governed
membership operation, expected version, fresh OA identity validation, audit
evidence, and EOS-to-OA entitlement synchronization.

## 5. Project-Code Authorization Identity

### W40-CA01-ADR-03: Use Project Code At The OA Resource Boundary

The authorization resource key is:

```text
(tenant_id, project_code)
```

Project code is suitable because application-created codes are immutable,
tenant-unique, human-readable, and already required in user-facing accounting
flows. Project code MUST NOT be evaluated without the tenant scope, even though
the code embeds a four-character tenant code.

The EOS UUID remains:

- the internal EOS primary/foreign key;
- a cross-service correlation and reconciliation reference; and
- a diagnostic field hidden from normal users.

It is not the resource identifier a person must copy or understand. OA may
retain `source_project_id` for lineage, but authorization requests, decisions,
audit displays, and denial messages use `project_code`.

Project codes are not aliases and cannot be renamed, recycled, or reassigned.
Exact tenant-scoped resolution is mandatory for protected writes.

## 6. OA Project Entitlement Projection

### W40-CA01-ADR-04: Add A Focused OA Project Grant Store

Use a focused Project grant structure rather than prematurely introducing a
general-purpose resource-policy engine. The logical minimum is:

```text
oa_project_grant
  tenant_id
  project_code
  subject_id
  project_role          OWNER | MANAGER | MEMBER | VIEWER
  grant_status          ACTIVE | REVOKED
  project_status        ACTIVE | INACTIVE | CLOSING | CLOSED
  source_project_id     UUID, lineage only
  source_version
  source_event_id
  source_event_hash
  granted_at
  revoked_at
  updated_at
```

The natural uniqueness boundary is:

```text
(tenant_id, project_code, subject_id)
```

The physical table and index design must support exact subject/Project lookup,
subject Project listing, active role filtering, idempotent source-event replay,
and stale-version rejection. Migration numbering is assigned only after the
current OA and EOS inventories are refreshed.

Project entitlement does not imply tenant-global accounting authority. A
Project member may access the admitted Project resource, but posting, approval,
policy administration, audit, payroll, and other privileged actions still
require their existing OA roles/scopes and SoD checks.

The full Project list MUST NOT be embedded in a long-lived signed access token.
Resource authorization uses an OA decision endpoint or an equivalent short-
lived, revision-bound decision. This keeps membership revocation observable and
prevents token growth as a user joins more Projects.

## 7. Synchronization Contract

### W40-CA01-ADR-05: EOS Outbox To OA Inbox Is The Grant Boundary

Final Project approval performs the following in one EOS transaction:

1. allocate the registration code;
2. insert the ACTIVE Project and approved party binding;
3. insert normalized owner, PM, and initial memberships;
4. append the existing Project lifecycle event for AE;
5. append an OA authorization event containing the exact normalized membership
   snapshot, source version, event identity, and digest; and
6. mark authorization synchronization `PENDING`.

EOS Project creation and OA application are not represented as one distributed
transaction. OA applies the event in its own transaction and ACKs the exact
event/version/digest. EOS then records `IN_SYNC`; terminal validation failure is
`FAILED` and remains operator-visible and replayable.

Later membership changes emit deltas or complete versioned snapshots with
equivalent semantics. Exact replay is a no-op. A repeated event with changed
content, a lower source version, unknown Project code, tenant mismatch, or hash
mismatch fails closed and creates operational evidence.

Reconciliation compares the EOS authoritative membership/version/digest with
the OA projection. Repair replays authoritative events; it does not silently
edit both databases or accept OA-only grants.

## 8. Lifecycle And Revocation Policy

| EOS Project state | OA entitlement behavior |
| --- | --- |
| `ACTIVE` | evaluate active grants and action-specific OA roles/scopes |
| `INACTIVE` | deny ordinary Project operations; retain projection for audit and later resume |
| `CLOSING` | allow only admitted closure capabilities for eligible roles |
| `CLOSED` | revoke execution capabilities; retain immutable audit history |

Member removal revokes that subject's grant. Role change is a versioned revoke
and grant transition or an equivalent atomic replacement. Owner/PM replacement
must not leave an ACTIVE Project without its required accountable roles.

An inactive, removed, or cross-tenant OA subject cannot retain an effective
Project allow decision even if a delayed EOS event remains pending. OA account
and tenant-membership state is evaluated together with the Project projection.

## 9. Authorization API And Fail-Closed Rules

The authorization request must identify at least:

```text
tenant_id
subject_id
project_code
action
request/evidence correlation
```

The decision returns an explicit allow/deny, Project role, applicable
tenant-global scopes, projection revision/source version, and reason code.

Normative denial conditions include:

- no exact OA Project grant;
- OA projection not synchronized or stale for a write requiring current state;
- subject inactive or not active in the tenant;
- Project inactive or closed for the requested action;
- Project role insufficient for the action;
- required global OA scope absent;
- tenant/Project-code mismatch; and
- malformed, unknown, replay-conflicting, or tampered evidence.

The current optional `project_ids` convention is not an admitted replacement.
Project-protected code must not interpret an absent collection as access to all
Projects. During migration, compatibility paths may translate a verified UUID
to the immutable Project code internally, but the OA decision remains bound to
the Project code.

## 10. W40 Accounting Admission Impact

W40 `S4-01` and later posting operations must require all of the following:

1. exact approved `project_code` and consistent internal `project_id`;
2. ACTIVE Project state, except for an explicitly admitted CLOSING operation;
3. current OA Project entitlement for the requester/action;
4. required tenant-global finance role/scope and fresh Human/SoD evidence;
5. completed or current-enough OA authorization synchronization under the
   admitted policy; and
6. existing approved-document, VoucherCandidate, accounting-period, FX, and
   balance validations.

Project membership alone never authorizes journal posting. Conversely, a
tenant-global finance scope without Project entitlement cannot authorize work
against that Project.

## 11. Compatibility And Migration Boundary

- EOS UUID primary/foreign keys remain unchanged.
- Project code remains the required user-facing identifier and authorization
  resource key.
- Existing `eos_project_member` rows remain the canonical membership source.
- Legacy direct-created Projects are not granted broad OA access by default.
  Their active memberships require an explicit, audited reconciliation/import
  event before protected new MyBee writes are enabled.
- Existing historical reads remain available under their prior contracts, but
  compatibility cannot bypass new W40 write authorization.
- Existing OA tenant roles, groups, scopes, signed-token, and introspection
  contracts remain intact.
- AE Project Agent synchronization remains a separate consumer and cannot be
  treated as proof that OA authorization is synchronized.
- No remote model provider is required for this controlled amendment or its
  authorization implementation.

## 12. Required Implementation Sequence

Implementation must proceed as focused Slices before W40 `S4-01`:

| Order | Slice | Required closure |
| --- | --- | --- |
| 1 | `W40-CA01-S01` | Project party and immutable initial-membership application contract |
| 2 | `W40-CA01-S02` | approval finalizer normalization and EOS membership materialization |
| 3 | `W40-CA01-S03` | OA Project-Code entitlement persistence and decision contract |
| 4 | `W40-CA01-S04` | EOS outbox, OA inbox, ACK, replay, and stale-version handling |
| 5 | `W40-CA01-S05` | EOS consumers migrated from optional Project scope to explicit fail-closed OA decisions |
| 6 | `W40-CA01-S06` | lifecycle revocation, reconciliation, actual PostgreSQL protected smoke, and W40 entry gate |

The exact Slice names may receive a short implementation suffix, but their
ordering and acceptance boundaries cannot be collapsed into mock-only tests.

## 13. Acceptance Matrix

At minimum, unit/regression tests and actual EOS/OA PostgreSQL protected smoke
must prove:

1. applicant, owner, and PM are three different active subjects;
2. one subject explicitly occupies applicant, owner, and PM roles;
3. applicant differs from PM and receives no Project access unless listed;
4. PM differs from owner and receives `MANAGER`, while owner receives `OWNER`;
5. inactive, unknown, duplicate, cross-tenant, or conflicting members fail
   before submission or approval as specified;
6. approval atomically creates one Project and the exact normalized membership
   set;
7. rejection creates no Project, membership, OA grant, or Project Agent;
8. exact finalization and delivery replay creates no duplicate membership or
   grant;
9. changed replay and stale source versions fail closed;
10. OA outage leaves authorization synchronization pending and protected writes
    denied, followed by successful replay and convergence;
11. member removal and role change update the OA decision;
12. ACTIVE/INACTIVE/CLOSING/CLOSED transitions enforce the lifecycle matrix;
13. Project code is used in authorization APIs and user-facing evidence while
    UUID remains internal lineage;
14. a Project member without finance scope cannot post;
15. a finance-scoped user without Project entitlement cannot post;
16. tenant mismatch and Project-code tampering are denied with zero mutation;
17. EOS/OA reconciliation detects and repairs missing projection rows without
    creating OA-only authority; and
18. existing OA, EOS Project membership, W30, and Golden A regressions remain
    green with required coverage margins.

## 14. Non-Goals

This amendment does not:

- replace EOS Project UUIDs or foreign keys with Project codes;
- make OA the editable business master for Project membership;
- introduce a general ABAC/policy-language engine;
- store all Project grants in long-lived access tokens;
- change the WC Project committee workflow;
- merge AE Project Agent synchronization with OA authorization sync;
- authorize Project-less accounting; or
- claim W40 implementation or acceptance complete.

## 15. Entry Decision

W40 `S4-01` remains blocked until `W40-CA01-S01` through
`W40-CA01-S06` produce implementation evidence and the protected EOS/OA
PostgreSQL gate passes.

The resulting invariant is:

```text
EOS authoritative Project membership
  -> durable Project-Code entitlement event
  -> OA idempotent authorization projection
  -> explicit OA allow for tenant + subject + project_code + action
  -> W40 accounting admission
```

No missing, delayed, optional, or UUID-only Project entitlement is interpreted
as permission.
