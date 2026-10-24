# P8.8 Pre-Entry Repository Consistency and Reliability Preparation Actions v1.0

**Status:** P8-CA03 CLOSED / P8-S76 and P8-S77 CLOSED / P8-S78 READY
**Phase:** P8.7A → P8.8 Transition
**Purpose:** Close small repository/configuration/evidence gaps before starting P8.8 Reliability / Reconciliation Closure
**Platform Repository:** `nurigitdev/2607_nex_platform`
**P8 Working Branch:** `transition/p4-agent-runtime-foundation`
**Reviewed Remote HEAD:** `04743258a999161eb161552557ae1c431a81bfe6`
**Reviewed Tree:** `5e75edd291d46bd517c662890b546032b27b6a03`
**HEAD Message:** `feat(p8): close voucher attachment integration`
**Date:** 2026-10-24

---

# 1. Purpose

Repository review confirmed that P8.7A is closed and the Platform is ready to
enter P8.8 from an architecture and implementation perspective.

Before beginning P8-S76, three small consistency/reliability preparation items
should be closed:

```text
PRE-01  Align Repository Full Gate coverage thresholds with P8 canonical policy.
PRE-02  Update P8 README with the current implementation/admission status.
PRE-03  Explicitly add attachment-bearing Voucher variants to the P8.8 reliability matrix.
```

These items do not change P8 architecture.

They align:

```text
configuration
documentation
reliability acceptance scope
```

with the actual P8.7A implementation baseline.

---

# 2. Current Reviewed Baseline

## 2.1 Branch State

Current P8 implementation line:

```text
branch = transition/p4-agent-runtime-foundation
HEAD   = 04743258a999161eb161552557ae1c431a81bfe6
tree   = 5e75edd291d46bd517c662890b546032b27b6a03
```

The reviewed branch is:

```text
180 commits ahead of master
0 commits behind master
```

Therefore P8 review and P8.8 implementation SHALL continue against the
transition branch unless a separate merge/freeze decision is made.

---

## 2.2 P8 Phase State

Repository evidence indicates:

```text
P8.1   CLOSED
P8.2   CLOSED
P8.2A  CLOSED
P8.3   CLOSED
P8.4   CLOSED
P8.5   CLOSED
P8.6   CLOSED
P8.7   CLOSED
P8.7A  CLOSED
P8.8   READY TO ENTER
```

P8.7A closure is recorded through:

```text
P8-S75A
...
P8-S75H
```

with P8-S75H recording the protected attachment journey closure.

---

## 2.3 P8.7A Protected Acceptance

P8.7A protected acceptance used:

```text
actual nex_ae_test PostgreSQL
actual nex_wc_test PostgreSQL
actual nex_oa_test PostgreSQL
actual nex_eos_test PostgreSQL
actual RustFS 1.0.1
```

and verified:

```text
multiple attachment upload
duplicate upload replay
restart recovery
partial-batch rejection
immutable manifest lock
post-lock mutation rejection
OA-authorized approval
EOS Voucher commit
exact attachment verification
manifest tamper rejection
cross-tenant substitution rejection
zero-residue cleanup
```

Protected journey result:

```text
1 passed
0 skipped
```

Repository Full Gate at P8.7A closure:

```text
pytest:              17,110 passed, 98 skipped
statement coverage:  96.76%
branch coverage:     96.14%
contracts:           191 schemas
                     253 positive examples
                     221 negative examples
                     9 OpenAPI documents
process exit code:   0
```

---

# 3. PRE-01 — Align Repository Full Gate Coverage Thresholds

## 3.1 Finding

P8-CA02 and the accepted P8 SRS define the canonical Platform Full Gate as:

```text
Statement Coverage >= 96%
Branch Coverage    >= 94%
```

However the current repository quality script still defaults to:

```text
STATEMENT_COVERAGE_MIN=95
BRANCH_COVERAGE_MIN=85
```

in:

```text
scripts/quality/run_quality_gate.sh
```

Current actual coverage is above both the old and new thresholds, so this is
not a current test failure.

The issue is governance consistency:

```text
SRS / CA02 says 96/94
but
Repository Full Gate currently enforces 95/85 by default
```

---

## 3.2 Required Action

Update the canonical default Full Gate thresholds to:

```text
STATEMENT_COVERAGE_MIN="${STATEMENT_COVERAGE_MIN:-96}"
BRANCH_COVERAGE_MIN="${BRANCH_COVERAGE_MIN:-94}"
```

This change is scoped to the Repository Full Gate in
`scripts/quality/run_quality_gate.sh`. The tiered Slice/Checkpoint Gate keeps
its independently selected `95 / 94` defaults. Changing that focused-gate
policy requires a separate decision and is not part of PRE-01.

---

## 3.3 Required Regression

After the change:

```text
run Repository Full Gate
confirm statement >= 96%
confirm branch >= 94%
confirm no exclusion manipulation
confirm no P8 protected gate regression
```

Recommended explicit negative/unit coverage-policy test:

```text
95.x statement → FAIL
93.x branch    → FAIL
96/94 or above → PASS
```

---

## 3.4 Exit Condition

```text
Repository Full Gate default
==
P8 canonical coverage policy
==
96 / 94
```

---

# 4. PRE-02 — Update P8 README Current Implementation Status

## 4.1 Finding

`docs/transition/P8/README.md` still contains historical entry-state text such
as:

```text
Documented NSL v0.2 Candidate = UNVERIFIED / NOT ADMITTED
Actual NSL v0.2 Admission     = NOT ESTABLISHED / P8-S01 REQUIRED
```

This was correct at CA02 entry time.

It is no longer the current implementation state.

The repository now contains an admitted NSL v0.2 lock:

```text
distribution    = nex-skill-language
package_version = 0.2.0
wheel            = nex_skill_language-0.2.0-py3-none-any.whl
wheel_sha256     = sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
```

and P8 has progressed through P8.7A.

---

## 4.2 Required Action

Do not rewrite or erase the historical CA02 explanation.

Instead add a new current-status section near the top of the P8 README.

Recommended:

```text
## Current Implementation Status

Reviewed Branch:
transition/p4-agent-runtime-foundation

Current P8 State:
P8.1   CLOSED
P8.2   CLOSED
P8.2A  CLOSED
P8.3   CLOSED
P8.4   CLOSED
P8.5   CLOSED
P8.6   CLOSED
P8.7   CLOSED
P8.7A  CLOSED
P8.8   NEXT

Current admitted NSL runtime:
nex-skill-language 0.2.0

Current attachment baseline:
P8-S75H CLOSED
```

---

## 4.3 Documentation Rule

Preserve the distinction:

```text
Historical entry decision
!=
Current implementation status
```

Do not modify CA02 historical findings merely because they were later resolved.

Add:

```text
resolved by P8-S01/P8-S02/...
```

or an equivalent status pointer.

---

## 4.4 Exit Condition

A developer opening `docs/transition/P8/README.md` can immediately determine:

```text
what was originally blocked
how it was resolved
what phase is currently closed
what the next implementation phase is
```

without reading all Slice documents first.

---

# 5. PRE-03 — Expand P8.8 Reliability Matrix for Attachment-Bearing Voucher

## 5.1 Finding

P8.7A explicitly hands off an attachment-bearing Voucher to P8.8.

P8.7A states that P8.8 fault injection SHALL include at least one
attachment-bearing Voucher scenario.

The original P8.8 Slice Plan includes:

```text
S76 UNKNOWN_COMMIT_STATE Fault Injection
S77 Reconciliation Outcomes
S78 COMMITTED + Verification FAILED
S79 COMMITTED + Verification UNKNOWN
S80 Outbox Publication ACK Loss
S81 Approval Event ACK Loss
S82 Worker Crash After Checkpoint
S83 Worker Crash After WRITE_REQUESTED
S84 Trust / Authorization Revocation
S85 Tamper / Cross-Tenant Matrix
S86 Full Reliability Protected Gate
```

Attachment is explicit mainly in S85.

P8.8 should also prove attachment identity stability across commit uncertainty
and verification failure.

---

# 6. Required Attachment-Bearing Reliability Variants

At minimum add the following variants.

## P8.8-A01 — Commit ACK Loss with Attachment Manifest

Flow:

```text
3 immutable RustFS objects
→ locked AttachmentManifest
→ NSL approval
→ WRITE_REQUESTED
→ EOS commits Voucher + 3 attachment associations
→ EOS response/ACK intentionally lost
→ AE observes UNKNOWN_COMMIT_STATE
→ reconciliation query
→ COMMITTED
```

Required assertions:

```text
Voucher count = 1
Attachment association count = 3
AttachmentManifestHash unchanged
Attachment IDs unchanged
RustFS object identities unchanged
no second EOS CREATE
no second RustFS upload
```

This SHOULD be part of P8-S76/P8-S77 protected acceptance.

---

## P8.8-A02 — Still-UNKNOWN Reconciliation with Attachments

Flow:

```text
attachment-bearing Voucher write
→ outcome unknown
→ reconciliation dependency unavailable/ambiguous
→ still UNKNOWN
```

Required:

```text
no CREATE retry
no attachment recreation
no manifest mutation
no cleanup of possibly committed immutable evidence
```

---

## P8.8-A03 — COMMITTED + Verification FAILED with Attachments

Flow:

```text
Voucher + attachments committed
→ verification returns deterministic FAILED
```

Required:

```text
commit remains COMMITTED
Voucher remains one
attachment associations remain exact
no new Voucher
no new AttachmentManifest
no new RustFS object
```

Recommended for P8-S78.

---

## P8.8-A04 — COMMITTED + Verification UNKNOWN with Attachments

Flow:

```text
Voucher + attachments committed
→ verification transport/dependency unavailable
→ VerificationStatus UNKNOWN
```

Required:

```text
no CREATE retry
no attachment upload retry
no attachment association rewrite
preserve original BusinessOperationId
preserve original manifest identity
```

Recommended for P8-S79.

---

## P8.8-A05 — Reconciliation Detects Attachment Lineage Drift

Inject mismatch in authoritative read/projection:

```text
expected manifest hash != observed manifest hash
or
expected attachment IDs != observed attachment IDs
```

Required:

```text
do not report VERIFIED
do not silently repair by mutation
do not recreate business transaction
surface reconciliation/verification failure
```

This can be included in P8-S85.

---

## P8.8-A06 — Cross-Tenant Attachment During Recovery

After an ambiguous write/recovery state, inject a cross-tenant object reference.

Required:

```text
fail closed
zero new mutation
no object disclosure
no tenant inference from object_ref string
```

---

# 7. P8.8 Core Invariants to Re-Prove

P8.8 SHALL prove the following using fault injection, not only unit-level
mapping.

```text
INV-01
UNKNOWN_COMMIT_STATE never triggers blind WRITE retry.

INV-02
Only EOS authoritative read may convert UNKNOWN to COMMITTED or NOT_COMMITTED.

INV-03
404 / transport failure / dependency failure does not prove NOT_COMMITTED.

INV-04
COMMITTED remains COMMITTED even when verification fails or is unknown.

INV-05
Verification never performs CREATE/UPDATE repair.

INV-06
BusinessOperationId remains stable across reconciliation.

INV-07
IdempotencyKey remains stable across recovery.

INV-08
ApprovalRequest / WriteIntent / PayloadHash lineage remains unchanged.

INV-09
AttachmentManifestHash remains stable across retry/recovery.

INV-10
RustFS object identity is not regenerated as part of business reconciliation.

INV-11
Outbox retry retries publication only, not business mutation.

INV-12
Approval event replay creates at most one semantic resume.

INV-13
Worker restart after WRITE_REQUESTED never assumes NOT_COMMITTED.

INV-14
Current trust/authorization revocation fails closed before any new protected action.
```

---

# 8. P8-S76~S86 Recommended Delta

The existing P8.8 numbering SHOULD remain unchanged.

Do not create a separate P8.8A phase unless implementation complexity requires
it.

Recommended enhancement:

```text
S76
UNKNOWN_COMMIT_STATE fault injection
+ attachment-bearing ACK-loss variant

S77
three reconciliation outcomes
+ exact attachment/manifest identity assertion

S78
COMMITTED + Verification FAILED
+ attachment-bearing variant

S79
COMMITTED + Verification UNKNOWN
+ attachment-bearing variant

S80
Outbox ACK loss
+ confirm attachment/Voucher mutation count unchanged

S81
Approval Event ACK loss
+ same manifest/approval binding preserved

S82
Crash after checkpoint
+ no duplicate approval/manifest semantic work

S83
Crash after WRITE_REQUESTED
+ attachment-bearing recovery path

S84
Trust / authorization revocation
+ protected attachment access remains fail closed

S85
Tamper / Cross-Tenant Matrix
+ manifest drift
+ attachment substitution
+ object_ref tenant isolation

S86
Full Reliability Protected Gate
+ at least one complete attachment-bearing reliability journey
```

---

# 9. P8-S86 Protected Gate Recommendation

P8-S86 should use actual:

```text
nex_ae_test
nex_wc_test
nex_oa_test
nex_eos_test
RustFS
```

At least one reliability journey SHOULD contain:

```text
actual immutable attachment objects
actual locked manifest
actual NSL approval lineage
actual EOS Voucher commit
injected ambiguous response
actual reconciliation
actual verification
zero duplicate business mutation
zero duplicate object creation
zero residue after cleanup
```

Remote LLM provider is not required for reliability semantics.

A deterministic fixture path is sufficient and preferable for mandatory
fault acceptance.

---

# 10. Additional Repository Observation — CI Status

At the reviewed HEAD:

```text
GitHub Actions workflow runs = none
GitHub commit status checks  = none
```

Current evidence therefore comes from repository-recorded local/Codex gates
and protected infrastructure smoke tests.

This is not a P8.8 blocker.

However, before:

```text
P8 Final Freeze
P9 Handoff
production/release branch protection
```

consider whether at least the Repository Full Gate should also be represented
as a remote enforced status/check.

This item is:

```text
RECOMMENDATION
not mandatory PRE-P8.8 action
```

unless release governance requires it.

---

# 11. Pre-P8.8 Action Checklist

```text
[x] PRE-01 update Repository Full Gate defaults to Statement 96 / Branch 94

[x] run Full Gate after PRE-01
[x] confirm coverage remains >= 96 / 94
[x] confirm no test exclusion/skip policy change

[x] PRE-02 update P8 README with current implementation status
[x] preserve historical CA02 text
[x] record admitted NSL v0.2 current state
[x] record P8.7A CLOSED / P8.8 NEXT

[x] PRE-03 update P8.8 reliability test matrix
[x] add attachment-bearing UNKNOWN_COMMIT_STATE scenario
[x] add attachment-bearing reconciliation scenario
[x] add attachment-bearing verification FAILED scenario
[x] add attachment-bearing verification UNKNOWN scenario
[x] add attachment lineage drift / cross-tenant recovery variants

[x] confirm P8-S76~S86 numbering unchanged
[x] confirm P8-S86 uses actual AE/WC/OA/EOS DB + RustFS
```

---

# 12. Exit Decision

PRE-01 through PRE-03 are closed. P8.8 implementation may begin.

Expected pre-entry state:

```text
Coverage policy      = repository-enforced 96 / 94
P8 README            = current-status aligned
P8.8 reliability set = attachment-aware
P8.7A protected base = preserved
```

Then:

```text
P8-S76
UNKNOWN_COMMIT_STATE Fault Injection
```

becomes the canonical next implementation Slice.

---

# 13. Final Position

No architecture blocker was found for P8.8.

The required pre-entry work is intentionally small:

```text
configuration consistency
+
documentation consistency
+
fault-acceptance scope consistency
```

The P8.8 objective remains:

> **Do not add a second safety mechanism. Deliberately break the already-built Controlled WRITE path and prove that the existing idempotency, commit-state, reconciliation, verification, approval, authorization, attachment integrity, and recovery boundaries preserve exactly one authoritative business outcome.**

---

# 14. P8-CA03 Closure Evidence

P8-CA03 closed on 2026-10-24 without a database migration, API contract
change, protected test exclusion, or remote model-provider dependency.

Focused policy and baseline regression:

```text
89 passed
1 protected opt-in skipped
contract validation = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
```

The P8-S75H protected journey was re-run against actual `nex_ae_test`,
`nex_wc_test`, `nex_oa_test`, and `nex_eos_test` PostgreSQL databases plus the
digest-pinned RustFS `1.0.1` image with SSE-S3 enabled:

```text
1 passed
0 skipped
zero test-row residue
zero test-object residue
```

The Repository Full Gate then ran without threshold overrides:

```text
pytest              = 17,111 passed / 98 skipped
statement coverage  = 96.76% / required 96.00%
branch coverage     = 96.14% / required 94.00%
contract validation = PASS
pytest duration     = 33m 55s
Full Gate exit      = 0
```

The 98 skips remain explicit protected/live opt-ins. P8-S75H has separate
zero-skip protected evidence above.

P8-S76 subsequently consumed this handoff and closed the attachment-bearing
ACK-loss fault-injection boundary. P8-S77 then used authoritative EOS reads to
prove `COMMITTED`, `NOT_COMMITTED`, and still-`UNKNOWN` outcomes. Across both
Slices, protected evidence recorded one EOS CREATE dispatch, one Voucher,
three attachment associations, stable manifest and RustFS object identities,
and zero residue. P8-S78 is now the next canonical Slice.
