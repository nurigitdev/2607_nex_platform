# NeX MyBee W40-CA02: Accounting Product Runtime Integration Checkpoint v1.0

## 1. Status And Authority

- Decision date: `2026-11-13`
- Status: `DESIGN_CLOSED_IMPLEMENTATION_REQUIRED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `de7209b2`
- Runtime code changes by this document: none

This controlled amendment defines a deliberately thin product-runtime
integration checkpoint between the completed W30/W40 foundations and W40
`S4-01` GL Posting.

It supplements, without rewriting:

- W30-CA02 Project application, code, lifecycle, and Project Agent contracts;
- W30 VoucherCandidate v2 creation, validation, review, and MyBee consumer;
- W40-CA01 EOS-owned Project membership and OA-owned Project-Code entitlement;
- the canonical installed platform runtime, signed service trust, PostgreSQL,
  outbox/inbox, worker, and deployment boundaries; and
- the D04/D12 Atomic GL Posting and Project Allocation Ledger design.

Where an earlier document can be read as permitting a test fixture, direct
database mutation, in-process fake transport, or mock authorization result as
proof of product integration, this document takes precedence for the W40
product-runtime entry gate.

## 2. Decision

Product integration is split into two stages.

### Stage A: integrate the existing accounting foundation now

The current W30/W40 implementation is admitted into the canonical installed
runtime using real service composition, signed service trust, actual
PostgreSQL databases, and durable event delivery. No new accounting feature is
created in this stage.

### Stage B: close the complete accounting product journey later

After GL Posting, PostedJournal/Ledger, Project Allocation Ledger, and Project
P&L are implemented, a second product acceptance closes the end-to-end
accounting journey.

Waiting until cost allocation to perform any installed integration is rejected.
It would combine authorization, Posting, allocation, deployment, and worker
failures into one debugging boundary. Activating unfinished GL or allocation
contracts now is also rejected.

## 3. Source-Backed Current State

The repository already contains product-code foundations rather than only test
harnesses:

| Boundary | Confirmed source state | Checkpoint obligation |
| --- | --- | --- |
| EOS application | `nex_eos.app` registers Finance v2, Project, approval, and reconciliation routes | prove the installed service exposes the admitted routes |
| EOS persistence | `build_eos_dependencies()` constructs PostgreSQL-backed VoucherCandidate, validation, review, Project, and authorization dependencies | prove production composition is used without fixture substitution |
| EOS to OA authorization | `EosProjectAuthorizationGate` uses an EOS Project context and an HTTP OA decision source when the EOS-to-OA token is present | make missing trust/configuration fail closed and prove explicit allow/deny |
| Entitlement delivery | EOS persists Project entitlement events and the installed outbox publisher supports OA delivery | prove worker routing, ACK, replay, stale-version rejection, and restart |
| OA projection | OA persists Project-Code grants and makes authorization decisions from EOS-derived entitlement plus current identity state | prove actual OA PostgreSQL convergence and revocation |
| MyBee consumer | MyBee owns an HTTP VoucherCandidate consumer while EOS remains the business SoR | prove the product consumer calls the installed EOS API, not a fake transport |
| Canonical platform | OA, EOS, WC, and the EOS outbox publisher already belong to the canonical deployment topology | extend or correct existing composition rather than create a parallel demo topology |

The remaining gap is therefore product assembly and installed evidence. This
checkpoint is not permission to duplicate repositories, authorization rules,
workers, or transaction coordinators.

## 4. Definition Of Thin Product Integration

The checkpoint is complete only when all of the following are true:

1. The canonical EOS service starts through its installed product entrypoint.
2. EOS uses the admitted EOS PostgreSQL database and current migrations.
3. OA uses the admitted OA PostgreSQL database and current migrations.
4. EOS obtains a signed, bounded-lifetime service credential for the exact OA
   audience and required scopes.
5. EOS Project entitlement events are delivered by the installed EOS outbox
   publisher to the OA inbox/API and exact ACKs update EOS synchronization.
6. The MyBee VoucherCandidate consumer calls the installed EOS Finance v2 API.
7. Project Code is the human-facing and authorization-facing resource key;
   Project UUID remains internal lineage.
8. An authorized Project member with the required finance scope is admitted.
9. A non-member, revoked member, inactive subject, stale projection, wrong
   tenant, wrong Project Code, or missing finance scope is denied with zero
   accounting mutation.
10. Restart and exact replay do not duplicate Project grants,
    VoucherCandidates, review cases, business operations, or outbox effects.

Direct test construction of repositories may remain in unit tests, but it is
not accepted as the installed product proof.

## 5. Target Installed Topology

```text
MyBee product consumer
  -> signed HTTP request
  -> NeX-EOS Finance v2 API
       -> EOS PostgreSQL
       -> signed OA Project authorization decision

EOS Project/membership mutation
  -> EOS PostgreSQL outbox
  -> installed EOS outbox publisher
  -> NeX-OA entitlement inbox/API
  -> OA PostgreSQL Project-Code grant projection
  -> exact ACK / EOS synchronization state

Existing BUSINESS_FORMAL review path, where exercised
  -> NeX-WC
  -> existing approval decision delivery
  -> NeX-EOS review projection
```

The checkpoint reuses the canonical single-host Docker Compose topology. It
does not add a MyBee-only compose stack, a second JobQueue implementation, a
second outbox publisher, or a demo runtime.

## 6. Required Product Composition

### 6.1 EOS API and dependency composition

- Reuse `nex_eos.app` and `build_eos_dependencies()`.
- Use the configured EOS database URL, OA base URL, signed service-token
  resolver/materialization, bounded timeout, and existing connection pool.
- Required dependencies must not silently fall back to permissive mocks.
- A route whose authoritative dependency is unavailable returns a typed,
  fail-closed unavailable response and performs no mutation.

### 6.2 EOS outbox publisher

- Reuse `nex_eos.outbox_publisher_process` and its durable claim/retry logic.
- Route Project lifecycle events to AE and Project entitlement events to OA by
  the canonical event type, not by test-specific ordering assumptions.
- An event is complete only after an exact event ID, version, and payload-hash
  bound receipt is validated.
- Retryable transport failures remain pending/retryable. Malformed, tampered,
  or semantically conflicting receipts fail closed and remain observable.

### 6.3 OA authorization projection

- Reuse the W40-CA01 OA Project grant and inbox structures.
- EOS remains the only business source for Project membership and lifecycle.
- OA evaluates current subject activity, tenant membership, Project grant,
  Project lifecycle, action, tenant-global finance scope, and SoD policy.
- OA-only manual Project grants remain prohibited.

### 6.4 MyBee consumer

- Reuse `NexVoucherCandidateClient` and the installed HTTP transport.
- The consumer passes canonical Project Code, proof-bound VoucherCandidate
  semantics, idempotency identity, and signed service/user context.
- Product execution must not import smoke fixtures or write EOS tables
  directly.

## 7. Persistence And Migration Boundary

This checkpoint expects no new database table by default.

It reuses:

- EOS Project, membership, application, authorization-version, business
  operation, VoucherCandidate, review, and outbox structures;
- OA identity, service principal, Project grant, inbox, and authorization
  evidence structures; and
- existing WC approval structures only where the current W30 review journey is
  exercised.

A migration is permitted only if source audit proves that installed product
composition cannot represent an already-approved W30/W40 contract. Convenience
columns, copied authorization state, and test-only receipts are not sufficient
reasons for a migration.

Actual `nex_eos_test`, `nex_oa_test`, and, where exercised, `nex_wc_test`
database identity must be admitted before migrations or mutation. Tests use
isolated schemas or a bounded tenant fixture and leave zero residue.

## 8. Security And Fail-Closed Rules

1. Service credentials are issued for the exact caller, audience, scopes, and
   bounded lifetime; credentials are not committed to the repository.
2. Browser code never receives EOS-to-OA or other service credentials.
3. Missing OA URL, token, trusted issuer/JWKS, database, or required migration
   blocks the protected product path.
4. Tenant and Project Code are checked independently even when the Project Code
   embeds a tenant prefix.
5. UUID, database URL, token, raw provider response, and private authorization
   internals are excluded from user-facing results and normal logs.
6. Authorization is obtained before opening a long EOS database transaction;
   no remote call is made while a Posting transaction is open.
7. Project membership never replaces finance scope or accounting SoD.

## 9. Explicit Non-Goals

This checkpoint does not implement or activate:

- GL Posting, `PostedJournal`, journal lines, ledger entries, or balances;
- AccountingApprovalAcceptance or final accounting approval execution;
- Project Allocation Ledger, allocation source pools, plans, batches, or lines;
- Project P&L, budget-versus-actual, allocation, or closing projections;
- payroll allocation, purchasing, inventory, manufacturing, or tax flows;
- new IA prompts, generation behavior, model-provider calls, or Agent planning;
- a new MyBee backend service or container image;
- a new UI workflow beyond preserving the already admitted consumer surface;
- replacement of the canonical platform deployment topology; or
- a claim that W40 or MyBee Phase-1 is complete.

Embedding, reranker, and generation providers are not required for this
checkpoint.

## 10. Proposed Implementation Slices

| Order | Slice | Required closure |
| --- | --- | --- |
| 1 | `W40-CA02-S01` | Product runtime composition and test/demo residue audit |
| 2 | `W40-CA02-S02` | Canonical installed configuration, signed trust, and process wiring |
| 3 | `W40-CA02-S03` | Installed EOS-to-OA entitlement delivery and MyBee consumer integration |
| 4 | `W40-CA02-S04` | PostgreSQL restart/replay/fail-closed protected acceptance and entry gate |

Each Slice is independently implemented, tested, committed, and synchronized.
The sequence may add a narrowly named corrective Slice when a real installed
gap is found, but must not absorb GL Posting or allocation scope.

## 11. Acceptance Matrix

The final protected acceptance must prove at least:

1. canonical service/process entrypoints pass readiness with current packages;
2. exact OA/EOS database and service identity admission succeeds;
3. all current migrations apply and a restart preserves authoritative state;
4. an approved Project materializes owner, PM, and member entitlements in OA;
5. EOS synchronization reaches `IN_SYNC` only after exact OA ACK;
6. an admitted member and finance-scoped requester can create and validate a
   Project-bound VoucherCandidate through the MyBee HTTP consumer;
7. a Project member without finance scope is denied;
8. a finance-scoped non-member is denied;
9. inactive, removed, cross-tenant, stale, tampered, and unknown Project cases
   are denied with zero VoucherCandidate mutation;
10. entitlement delivery failure remains pending and the protected write is
    denied until replay converges;
11. exact command and event replay returns the same logical result without
    duplicate records;
12. changed replay returns conflict and performs no additional mutation;
13. worker and service restart resume pending delivery without loss;
14. logs and evidence contain stable business references and no credentials or
    private payloads;
15. focused unit/regression, actual PostgreSQL protected smoke, contract
    validation, and Repository Full Gate pass; and
16. all temporary schemas, tenant fixtures, sessions, and test records are
    removed or deterministically restored.

No hard-coded smoke orchestration result is accepted as evidence that the
installed runtime performed the journey.

## 12. Rollback And Compatibility

- Existing historical reads and Golden A behavior remain compatible.
- Existing W30/W40 schemas and APIs remain canonical; this checkpoint favors
  composition changes over business-contract changes.
- Product activation is configuration-bound and may be rolled back to the
  previous installed composition without deleting authoritative data.
- Rollback must not remove or weaken OA Project entitlements, W40 fail-closed
  authorization, or mandatory Project attribution.
- Pending outbox/inbox state is reconciled before and after rollback.
- A failed integration attempt does not authorize direct database fallback.

## 13. W40 S4 Entry Decision

W40 `S4-01` GL Posting may begin only after `W40-CA02-S01` through
`W40-CA02-S04` demonstrate that the current accounting foundation operates in
the canonical installed product path.

The resulting invariant is:

```text
implemented W30/W40 business contract
  -> canonical product dependency composition
  -> signed cross-service trust
  -> actual PostgreSQL authority
  -> durable worker delivery and restart-safe replay
  -> installed MyBee-to-EOS acceptance
  -> S4-01 GL Posting entry
```

After GL Posting and Project Allocation are implemented, a separate final
accounting product acceptance must connect PostedJournal, allocation, Project
P&L, operations, and user-facing E2E. Passing this thin checkpoint does not
pre-approve that later closure.
