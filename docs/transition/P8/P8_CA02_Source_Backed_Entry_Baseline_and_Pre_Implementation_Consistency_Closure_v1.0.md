# P8-CA02 - Source-Backed Entry Baseline and Pre-Implementation Consistency Closure

**Status:** ACCEPTED PRE-IMPLEMENTATION CONSISTENCY CLOSURE / CONDITIONAL P8 ENTRY
**Date:** 2026-10-21
**Phase:** P8 - Controlled WRITE / Approval / Delegation / Enterprise OS
**Predecessor:** P8 initial design document set at Platform commit `470db09c0d11e226a830661d7c99d6325ca17374`
**Platform Baseline Tree:** `651cf522e1d8688aac66f1a9e4a949772e51682d`
**Purpose:** Close source-backed entry inconsistencies before P8-S01 and make unresolved release provenance fail closed

---

# 1. Decision Scope

P8-CA02 freezes only the following pre-implementation decisions:

```text
1. actual NSL source/wheel entry baseline
2. CA01 and CA01A formal acceptance status
3. canonical coverage thresholds
4. Platform ApprovalEvidence persistence ownership
5. Golden A Project/Account/voucher-line resolution rules
6. RustFS object_ref and tenant-validation boundary
```

It does not replace the P8 SRS or implementation plan. It is an additive
consistency closure that must be read after CA01A and before the SRS.

---

# 2. Authority and Conflict Rule

For the six decisions in this document, authority is:

```text
Frozen integrated authority
> Frozen machine-readable contracts
> P8-CA02
> P8-CA01 / P8-CA01A
> P8 SRS
> P8 Implementation Slice Plan
> implementation convenience
```

P8-CA02 does not override Frozen authority. If a CA02 decision conflicts with
Frozen authority, implementation must stop and use a controlled amendment.

For all P8 concerns outside the six decisions, the existing P8 authority order
continues unchanged.

---

# 3. Closure Summary

```text
CA02-DEC-01  The claimed NSL v0.2 source/wheel is not currently admissible.
CA02-DEC-02  The observed NSL checkout and admitted v0.1 wheel are evidence,
              not substitutes for an NSL v0.2 release.
CA02-DEC-03  P8-S01 must establish the exact v0.2 source and wheel lock before
              any v0.2 runtime activation or P8.1 acceptance claim.
CA02-DEC-04  CA01 and CA01A are formally accepted with CA02 overrides.
CA02-DEC-05  Platform Full Gate is Statement >= 96%, Branch >= 94%.
CA02-DEC-06  NSL native release gate is Statement >= 99%, Branch >= 98%.
CA02-DEC-07  AE owns canonical immutable Platform ApprovalEvidence.
CA02-DEC-08  WC owns the human task/decision, OA owns authorization evidence,
              and EOS owns BUSINESS_FORMAL proof.
CA02-DEC-09  LLM output may propose business-reference candidates but cannot
              establish ProjectRef, AccountRef, or authoritative voucher lines.
CA02-DEC-10  Golden A uses tenant-scoped deterministic reference resolution,
              explicit ambiguity handling, and a balanced line policy.
CA02-DEC-11  Cross-service object_ref is owner-issued and opaque; consumers do
              not infer tenant ownership from its text.
CA02-DEC-12  EOS associates an attachment only after a fail-closed authoritative
              resolver proves tenant, purpose, existence, state, and metadata.
```

---

# 4. Actual NSL Source and Wheel Baseline

## 4.1 Source-Backed Observation

The source audit was repeated on 2026-10-21 against:

```text
repository: nurigitdev/2608_nsl
local path: /home/tprover/2608_nsl
active branch: codex/p6-ca02-nsl-wheel-admission
HEAD: 3b4cb198888570a857e6fb0d3aa077930bb23504
tree: 03a08902a4b852709265ba9c15bcd312ef48f9da
pyproject package version: 0.1.0
working tree: clean at audit time
```

The remote branch resolves to the same commit. The remote exposes tag `v0.1`
and does not expose a v0.2 tag or a ref containing the P8-documented commit.

The commit previously named as the certified v0.2 source:

```text
5cd81e18ffbedeee83605cd2e6a6cbcab54c1fb6
```

is not present in the audited local object database and is not advertised by
the audited remote refs. Its documented tree cannot therefore be independently
verified from the available source.

## 4.2 Existing Admitted Wheel

The Platform has one source-backed NSL lock:

```text
lock: deployment/locks/nsl-v0.1-wheel.json
distribution: nex-skill-language
package version: 0.1.0
source revision: 3b4cb198888570a857e6fb0d3aa077930bb23504
wheel: nex_skill_language-0.1.0-py3-none-any.whl
wheel SHA-256: sha256:290a202f540ec98291842e9281a28288cc7ac112525b6c0f02c10b8721aef21f
Python requirement: >=3.12
locked cryptography: 46.0.7
```

This lock remains valid for the existing `NSL_V01_IN_PROCESS` profile. It must
not be renamed, relabeled, or treated as an NSL v0.2 artifact.

## 4.3 Canonical v0.2 Decision

At CA02 closure time:

```text
actual admitted NSL v0.2 source baseline = NOT ESTABLISHED
actual admitted NSL v0.2 wheel baseline  = NOT ESTABLISHED
P8 v0.2 runtime activation               = BLOCKED BY P8-S01
```

This is a controlled entry condition, not permission to bypass v0.2.

## 4.4 P8-S01 Admission Tuple

P8-S01 must produce a committed `deployment/locks/nsl-v0.2-wheel.json` only
after one protected admission run proves all of the following:

```text
repository identity
clean exact source revision
exact source tree
explicit v0.2 package version; 0.1.0 is not acceptable
reproducible wheel filename and SHA-256
wheel METADATA / WHEEL / RECORD integrity
Python requirement
dependency compatibility with the Platform lock
imports from installed wheel, never source-checkout sys.path injection
required public v0.2 READ / CHECK / WRITE / approval symbols
NSL native Full Gate at Statement >= 99%, Branch >= 98%
```

The previously documented `5cd81e18...` value may be admitted only if the
actual source object and matching wheel are supplied and independently pass
this gate. Documentation alone is not release evidence.

## 4.5 Stop Conditions

The following are prohibited before P8-S01 passes:

```text
selecting NSL_V02_IN_PROCESS as ready/default
creating a lock with placeholder source or wheel hashes
using the v0.1 wheel under a v0.2 profile name
claiming P8.1 or Golden A acceptance
executing an authoritative WRITE through an unadmitted NSL package
```

Source-independent design and test-fixture work may continue, but it must stay
clearly marked as non-admitted and cannot satisfy the protected v0.2 gate.

---

# 5. Formal Acceptance State

The initial document set intentionally preserves its original status labels.
This closure supplies the formal acceptance record without rewriting history.

| Document | Formal P8 State After CA02 | Qualification |
|---|---|---|
| P8 Pre-Architecture Decision v1.0 | ACCEPTED AS DESIGN INPUT | Its 95/90 and 98/96 coverage values are superseded by Section 6. |
| P8 Source Audit v1.0 | ACCEPTED WITH SOURCE-PROVENANCE CORRECTION | Its claimed NSL v0.2 commit/tree and standalone acceptance are not release evidence. |
| P8-CA01 v1.0 | ACCEPTED WITH CA02 OVERRIDES | DEC-01 is conditional on actual P8-S01 artifact admission. |
| P8-CA01A v1.0 | ACCEPTED WITH CA02 OVERRIDES | The opaque-reference resolver rule in Section 9 completes DEC-22. |
| P8 SRS v1.0 | ACCEPTED AS IMPLEMENTATION REQUIREMENTS | CA02 wins for the six closure topics. |
| P8 Implementation Slice Plan v1.0 | ACCEPTED AS EXECUTION PLAN | P8-S01 remains the mandatory first implementation gate. |

Therefore:

```text
CA01 formal acceptance  = ACCEPTED WITH CA02 OVERRIDES
CA01A formal acceptance = ACCEPTED WITH CA02 OVERRIDES
P8 implementation entry = CONDITIONAL ON SLICE-SPECIFIC PREREQUISITES
P8 v0.2 runtime entry    = BLOCKED UNTIL P8-S01 PASS
```

---

# 6. Canonical Coverage Policy

## 6.1 Platform Repository

The required minimum at a Platform Full Gate is:

```text
Statement Coverage >= 96%
Branch Coverage    >= 94%
```

This is the canonical P8 release threshold. Existing higher observed coverage
must be protected through focused tests; 96/94 is not a target for deliberate
coverage reduction.

## 6.2 NSL Repository

The NSL-native release gate remains:

```text
Statement Coverage >= 99%
Branch Coverage    >= 98%
```

P8 must not weaken the independent NSL gate to make package admission pass.

## 6.3 Superseded Values

The Pre-Architecture values are interpreted as follows:

```text
95/90 = early Frozen target, superseded for P8 admission
98/96 = desired Platform quality posture, not the canonical minimum gate
96/94 = canonical Platform Full Gate minimum
99/98 = canonical NSL native release gate minimum
```

## 6.4 Gate Cadence

P8 continues the established discipline:

```text
every Slice: focused unit/regression + applicable bounded coverage
fifth Slice checkpoint: Checkpoint Gate
tenth Slice or phase closure: Repository Full Gate
protected PostgreSQL/provider/object-storage smoke: when the Slice claims that
actual boundary
```

No skip, exclusion, or threshold change may be used to represent unavailable
infrastructure as passing evidence.

---

# 7. Platform ApprovalEvidence Persistence Ownership

## 7.1 Canonical Owner

AE is the system of record for:

```text
the exact protected NSL ApprovalRequest checkpoint
the canonical immutable Platform ApprovalEvidence record
the link from AgentExecution / ExecutableStep / NSLExecution to that evidence
the deterministic NSL ApprovalEvidence projection
resume-time evidence verification result
```

The authoritative evidence row and integrity metadata are persisted in AE
PostgreSQL. If a protected request body is too sensitive or large for inline
storage, AE private storage may hold the body and AE PostgreSQL stores its
opaque reference, hash, size, media type, and immutable binding. The canonical
evidence identity and ownership do not move to object storage.

## 7.2 Other Service Ownership

```text
WC  -> ApprovalWorkItem, assignment, human decision, decision event
OA  -> approver identity, current authorization decision/evidence
EOS -> BUSINESS_FORMAL policy, instance, stage decision, and ApprovalProof
AE  -> Platform ApprovalEvidence joining those references for NSL resume
```

WC, OA, and EOS may retain their own authoritative records. They do not persist
a second mutable copy of AE's canonical Platform ApprovalEvidence.

## 7.3 Evidence Construction Rule

AE may construct the canonical record only after it can bind:

```text
same tenant_id
same agent_execution_id / executable_step_id
same nsl_execution_id / business_operation_id
same approval_request_id / skill_semantic_hash
same payload_hash / write_intent_hash
terminal WC decision
fresh OA authority evidence
protected original request reference
```

The record is append-once and immutable. Duplicate construction with identical
semantics is idempotent. Reuse of an evidence identity with different semantics
is a conflict and must fail closed.

## 7.4 Projection and Verification

AE projects only the certified NSL public `ApprovalEvidence` fields. It never
allows a Platform field to override original NSL request bindings.

The verifier resolves AE evidence by stable reference and proves the referenced
WC and OA records. Missing, expired, cross-tenant, unavailable, or mismatched
authority blocks resume. A cached upstream ALLOW does not override a current
DENY or unavailable required authority source.

## 7.5 Implementation Naming

This closure freezes ownership and semantics, not final table names. P8
implementation may select concise AE-owned table names after migration review.
It must not introduce a generic cross-service shared approval database.

---

# 8. Golden A Deterministic Business Resolution

## 8.1 Authority Boundary

LLM output is non-authoritative for:

```text
ProjectRef
AccountRef
voucher line direction
counter-account selection
authoritative amount/currency/date
```

The LLM may provide normalized search terms and candidate intent. Stable
business references and lines are produced by deterministic Platform/EOS
capabilities and validated again by EOS before mutation.

## 8.2 Project Resolution

Project resolution is tenant-scoped and uses this order:

```text
1. supplied stable ProjectRef -> verify tenant, active/effective state, type,
   hierarchy, and eligibility
2. exact tenant-unique project code -> resolve to stable ProjectRef
3. display/search term -> list bounded candidates only
```

For a display/search term:

```text
zero candidates     -> request user clarification; no WRITE intent admission
one eligible match  -> present it and require explicit user confirmation
multiple candidates -> require explicit user selection; no implicit ranking win
```

Only a caller-supplied stable ProjectRef from a trusted selection context or an
exact tenant-unique project code may bind without an additional display-name
confirmation. An LLM confidence score, first search result, default Project, or
cross-tenant name match must not establish the authoritative ProjectRef.

## 8.3 Account Resolution

Account resolution follows the same stable-reference rule and additionally
requires:

```text
tenant/ledger scope match
active and effective Account
allowed use for the selected voucher policy/category
exact stable account_id in the admitted payload
```

A unique exact account code may resolve deterministically. A display name or
category label is only a candidate. Zero or multiple eligible accounts require
policy correction or explicit user selection.

## 8.4 Voucher-Line Construction

Golden A uses a versioned deterministic voucher-line policy. The policy maps:

```text
(tenant, voucher_type, economic_category, settlement_method, effective_at)
-> debit AccountRef
-> credit AccountRef
-> line construction rule
```

For the representative travel-expense scenario, acceptance fixtures must seed
one explicit policy mapping and stable active accounts. The prompt text alone
must not invent the settlement side. If settlement method or required policy
input is absent, IA requests clarification before approval publication.

The initial two-line rule is:

```text
amount = positive decimal Money normalized to the currency scale
line 1 = policy debit AccountRef,  +amount
line 2 = policy credit AccountRef, -amount
sum(signed_amount) == 0
line order = deterministic by policy role then stable line number
```

Equivalent explicit debit/credit columns are allowed only if their canonical
payload and balance rule are equally deterministic.

## 8.5 Hash and Approval Timing

Canonical ProjectRef, AccountRefs, lines, amount, currency, date, and optional
attachment refs are resolved before:

```text
PayloadHash
WriteIntentHash
ApprovalRequest publication
```

A material change after approval invalidates the old binding and requires a
new approval flow. Display labels may be retained for UX but are not hash or
mutation authority unless the canonical schema explicitly includes them.

## 8.6 EOS Revalidation

Immediately before mutation, EOS independently checks:

```text
tenant scope
Project active/effective/hierarchy eligibility
Account active/effective/policy eligibility
decimal validity and currency consistency
line balance
payload and intent hashes
current OA authorization
idempotency and approval bindings
```

Any unresolved, ambiguous, stale, cross-tenant, or unbalanced input produces
zero business mutation.

---

# 9. RustFS object_ref and Tenant Validation Boundary

## 9.1 Reference Semantics

The cross-service `object_ref` is a stable, versioned, owner-issued opaque
identifier. Consumers store and compare it as an indivisible value.

The exact textual encoding is intentionally left to the storage-owner contract
slice. Regardless of encoding, it must not be:

```text
a presigned URL
an access or secret key
a session credential
a local filesystem path
a caller-constructed bucket/key pair
```

An internal `s3://bucket/key` storage URI may exist inside the owning service,
but it is not the cross-service ownership proof and must not be parsed by EOS to
infer tenant identity.

## 9.2 Authoritative Resolver

The service that owns the object metadata exposes an authenticated resolver
equivalent to:

```text
resolve_object_ref(
    requester_service,
    tenant_id,
    object_ref,
    required_purpose="EOS_VOUCHER_ATTACHMENT",
)
```

The verified result contains bounded metadata:

```text
object_ref
storage_owner
tenant_id
subject/owner reference where policy permits
purpose
status
content_sha256
size_bytes
media_type
immutable version reference where available
```

No object bytes, credentials, or presigned URL are returned to EOS for
association validation.

## 9.3 Fail-Closed Validation

Before inserting an EOS voucher-attachment association, EOS must obtain a
fresh resolver result proving:

```text
reference exists
resolver response is authenticated
tenant_id exactly matches the Voucher tenant
purpose permits EOS Voucher attachment use
object is active, immutable, and not deleted/quarantined
hash/size/media metadata match supplied association metadata
```

The following produce zero association and zero voucher mutation when the
attachment is part of the same atomic request:

```text
resolver unavailable
unknown reference
cross-tenant reference
wrong purpose
deleted/quarantined object
metadata mismatch
```

RustFS `HEAD` success alone is insufficient tenant evidence. Existing object
keys use one-way owner digests and are not an authorization interface.

## 9.4 Ownership Split

```text
storage owner -> object bytes, internal bucket/key, immutable object metadata
EOS           -> Voucher attachment association and copied bounded metadata
RustFS        -> S3-compatible byte persistence
```

For the first integration, an AE-owned upload may supply the object reference
if AE is the authoritative metadata owner and implements the resolver contract.
This does not transfer Voucher business ownership from EOS to AE.

## 9.5 Golden A Boundary

Attachments remain optional in Golden A. A no-attachment scenario does not
require live RustFS evidence. Once a Golden A scenario supplies an attachment,
the resolver and actual RustFS-backed existence/integrity checks become
mandatory protected evidence.

---

# 10. Required Implementation Consequences

The Slice Plan remains valid with these mandatory interpretations:

```text
P8-S01 -> establish actual v0.2 source/wheel admission; no placeholder lock
P8-S16 -> define owner-issued object_ref plus resolver contract before live use
P8-S48 -> implement AE-owned canonical Platform ApprovalEvidence store
P8-S49 -> project AE evidence to the admitted NSL public contract
P8-S13/S14 -> implement tenant-scoped Project/Account resolution sources and
               stable-reference validation
P8-S15/S18 -> implement the versioned balanced voucher-line rule in the
               aggregate and machine-readable command contract
P8-S19/S62 -> perform EOS pre-mutation revalidation and prove zero-mutation
               negative cases at the controlled WRITE gate
P8-S63/S64 -> seed deterministic Project/Account/line-policy mappings and
               enforce LLM candidate-only plus ambiguity-stop behavior
```

This mapping replaces an earlier incorrect reference to P8-S59/S60/S61. Those
Slices retain their original responsibilities:

```text
P8-S59 -> Commit Outcome Mapping
P8-S60 -> Reconciliation Adapter
P8-S61 -> PostWriteVerificationPort Adapter
```

The correction changes only Slice ownership references. It does not change the
Golden A decisions in Section 8 or the original Slice Plan responsibilities.

If the current Slice Plan uses the generic phrase "Platform Approval Evidence
Store", it means the AE-owned store defined in Section 7.

---

# 11. Acceptance Matrix

| ID | Required evidence | Expected result |
|---|---|---|
| CA02-01 | NSL documented v0.2 commit cannot be resolved | v0.2 remains NOT ESTABLISHED |
| CA02-02 | Existing v0.1 lock matches source-backed P6 admission | retained only for v0.1 profile |
| CA02-03 | Future v0.2 exact source/wheel admission | required PASS in P8-S01 |
| CA02-04 | CA01/CA01A status record | ACCEPTED WITH CA02 OVERRIDES |
| CA02-05 | Platform gate policy | 96/94 minimum |
| CA02-06 | NSL gate policy | 99/98 minimum |
| CA02-07 | Evidence ownership review | AE canonical owner; WC/OA/EOS referenced SoRs |
| CA02-08 | Duplicate evidence same semantics | idempotent |
| CA02-09 | Duplicate evidence changed semantics | conflict / fail closed |
| CA02-10 | Ambiguous Project or Account | clarification; zero WRITE |
| CA02-11 | Missing settlement policy input | clarification; zero WRITE |
| CA02-12 | Deterministic two-line fixture | exact refs and sum zero |
| CA02-13 | Cross-tenant object_ref | denied; zero association/mutation |
| CA02-14 | Resolver unavailable or metadata mismatch | fail closed |

---

# 12. Non-Goals

P8-CA02 does not implement:

```text
NSL v0.2 source or wheel
EOS service/database
accounting policy administration UI
general ERP account determination
full document management
RustFS upload/download routes
BUSINESS_FORMAL multi-stage workflow
database migrations or runtime code
```

Those remain assigned to P8 implementation slices.

---

# 13. Closure Decision

P8 pre-implementation consistency is closed for the six scoped decisions.

The design set is accepted for controlled implementation, subject to this
non-negotiable first runtime gate:

```text
P8-S01 must establish and admit a real NSL v0.2 source/wheel baseline.
Until then, NSL v0.2 runtime activation and P8.1 acceptance fail closed.
```

The next implementation entry remains:

```text
P8-S01 - Actual NSL v0.2 Wheel Identity Closure
```
