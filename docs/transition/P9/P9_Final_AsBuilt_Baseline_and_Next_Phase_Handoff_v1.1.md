# P9 Final As-Built Baseline and Next-Phase Handoff v1.1

**Status:** FINAL / P9 FOUNDATION CLOSED / P9-CA04 PASS / P9-S31A PASS

**Phase Closed:** P9 - NeX-WA Work Evidence and Work Asset Foundation

**Next Phase:** Not selected; controlled decision required

**Observed Date:** 2026-10-28

**Platform Branch:** `transition/p4-agent-runtime-foundation`

## 1. Purpose and Version Lineage

This document supersedes v1.0 as the canonical P9 handoff after the bounded
P9-S31A privacy classification correction. It does not rewrite history:

```text
v1.0 = historical P9-S31 freeze
v1.1 = corrected executable baseline and revalidated handoff
```

P9 remains a post-work evidence foundation. It is not a scheduler, approval
engine, Human-effort authority, payroll source, accounting system, or Project
profitability calculation.

## 2. Corrected Executable Baseline Identity

```text
repository     = nurigitdev/2607_nex_platform
branch         = transition/p4-agent-runtime-foundation
commit         = a4ef2f76d2b34e937f8e30316743302126c435ed
tree           = 1a16ed5dbabfa9060bdbb045845bbc1c665d500c
contracts tree = 9fdf95175cbcaf22c13fca81009ccd26c69578e9
```

The P9-S30 executable baseline `bc28307a58b659c791211d995ea773c77ef786c0`
and the P9-S31 v1.0 record remain historical acceptance evidence. P9 entry for
any later phase means the corrected commit above or a verified descendant that
preserves its runtime and privacy contract.

## 3. Closed Foundation Path

The corrected source-backed path is:

```text
completed AE AgentResult / READY AE Artifact
-> signed reference-only WA intake
-> service-local PostgreSQL JobQueue
-> fenced evidence consumer
-> source projection re-verification

background AgentResult
-> exact WC WorkResult resolution by AgentExecution / Claim lineage
-> WC_WORK_RESULT SUPPORTING WorkEvidence

-> immutable WorkEvidence
-> bounded WorkAsset and PRIMARY/SUPPORTING binding
-> replay-safe read, reconciliation, correction, and operations surfaces
```

External WA intake is `AE_AGENT_RESULT` and `AE_ARTIFACT`. WC WorkResult is
resolved as supporting evidence for a verified background AgentResult; it is
not a mandatory independent external WA ingress in the P9 Foundation.

OA retains Human identity authority, AE retains Agent execution and Artifact
authority, WC retains WorkResult lineage authority, and EOS retains Project
and membership authority. WA stores admitted references, hashes,
classification, authority snapshots, and lineage only.

## 4. P9-S31A Corrective Closure

The source contract requires WA classification to be the same as the
authoritative source or more restrictive, never less restrictive. The frozen
runtime incorrectly assigned `INTERNAL` to AgentResult-derived evidence and
assets when the source exposed no compatible classification.

P9-S31A corrected only that default:

```text
AE AgentResult PRIMARY WorkEvidence   = CONFIDENTIAL
Agent WorkAsset                       = CONFIDENTIAL
WC WorkResult SUPPORTING WorkEvidence = CONFIDENTIAL
Artifact INTERNAL                     = CONFIDENTIAL
Artifact CONFIDENTIAL                 = CONFIDENTIAL
Artifact RESTRICTED                   = RESTRICTED
```

WorkEvidence and WorkAsset deterministic IDs, source equivalence,
PRIMARY/SUPPORTING bindings, completion barriers, Project verification, and
Claim lineage are unchanged. Because classification participates in semantic
hashes, corrected records have new deterministic evidence and asset hashes;
exact replay under the corrected rule remains stable.

No migration, table, OpenAPI field, JSON Schema field, source type, Job type,
scope, service, or authorization model was added.

## 5. Contract and Database Baseline

Canonical contract validation remains:

```text
JSON schemas      = 226
positive examples = 290
negative examples = 244
OpenAPI documents = 10
contract tree     = 9fdf95175cbcaf22c13fca81009ccd26c69578e9
```

The source and actual `_test` PostgreSQL migration inventories remain
`171 / 171` across OA, AE, CX, MO, AG, WC, EOS, and WA. NeX-WA remains at
`8 / 8` migrations with head `2607_wa_service_logs`. No cross-service foreign
key, direct cross-service database read, second WA queue, or contribution
candidate table was introduced.

## 6. Installed Topology

The deployment catalog remains nine immutable artifacts and seventeen process
bindings. P9 owns `nex-wa-api` and the installed, supervised,
`job_claiming` `nex-wa-evidence-consumer`. The accepted S27 WA image identity,
non-root user, read-only filesystem, network-none entrypoint check, and no
registry-push boundary remain unchanged from v1.0.

## 7. Verification and Acceptance

```text
focused S17/S18/S19/S20 regression = 68 passed, 1 protected skip
protected PostgreSQL acceptance    = 41 passed
NeX-WA Slice Gate                   = 319 passed, 12 protected skips
Slice statement coverage           = 97.31% (required 96.00%)
Slice branch coverage              = 94.70% (required 94.00%)
Repository Full Gate               = 18,268 passed, 131 protected skips
Full statement coverage            = 96.01% (required 96.00%)
Full branch coverage               = 95.22% (required 94.00%)
AE Web Node regression             = PASS
contract validation                = 226 / 290 / 244 / 10
Full Gate exit code                = 0
```

Relative to the accepted P9-S30 Full Gate, four additional tests pass. The
protected skip count and both full-repository coverage percentages are
unchanged. The increase is explained by privacy-default, identity/hash, and
persisted-classification assertions.

Protected acceptance used the actual AE, WC, OA, EOS, and WA test databases
with signed service trust and verified completion barriers, source
equivalence, fencing, privacy scopes, cross-tenant denial, and idempotent
replay.

## 8. Evidence Identities

```text
protected acceptance JUnit sha256 = e7a966ab335bf145ae279fe58715b2fe58d488d5e436681d1f772787062e6551
NeX-WA Slice coverage sha256       = 12cbe97d8784bf39fbbfb53e076743fe2d238959331504016cff5dfd29760205
Full Gate coverage JSON sha256     = 0e4f3a47a127b5e0d701b5ca5f0bab6c2604f33ca1853aa45fe724dcd4a3746e
Full Gate JUnit sha256             = 9254daa340a78eafc8283578fc886b94ceff78e7f774ae1564634b4fc0973795
```

The report files remain local ignored artifacts. Their hashes bind this record
to the accepted runs without committing environment-specific output.

## 9. Historical Data and Zero Residue

The local pre-correction inventory found no retained affected rows in
`nex_wa_test`; `nex_wa_dev` has no WA schema. Staging and production were not
in scope. Therefore no historical record was silently rewritten and no data
remediation is authorized by this closure.

After the protected rerun, tenant-scoped residue was:

```text
nex_wa_test  = 0
nex_ae_test  = 0
nex_wc_test  = 0
nex_oa_test  = 0
nex_eos_test = 0
```

## 10. Frozen P9 Invariants

1. WA is post-work evidence and is not the Work system of record.
2. WA is not a Scheduler and does not read or mutate another service database.
3. Evidence admission is not Approval and creates no Approval or WC Delegation.
4. P9 Foundation has no NSL runtime dependency.
5. Positive Agent evidence requires the authoritative completion/publication
   ACK barrier.
6. Source equivalence and semantic idempotency are independent of JobQueue
   delivery idempotency.
7. Stale-worker recovery fences the former lease owner's settlement authority.
8. Basic, detail, audit, and operations privacy scopes remain separate.
9. Human ownership never implies Human effort, contribution, salary, cost, or
   Project profitability.
10. AgentResult and WC supporting evidence without an explicit compatible
    authoritative source classification default to `CONFIDENTIAL`.
11. Artifact classification is preserved or strengthened; WA never silently
    downgrades source sensitivity.
12. Future autonomous authority profiles fail closed unless admitted by a
    controlled contract amendment.

## 11. P9.5 and Next-Phase Disposition

```text
P9-C01 Candidate Contract / Method Registry = DEFERRED
P9-C02 Deterministic Candidate Calculation  = DEFERRED
P9-C03 Golden C Candidate Handoff            = DEFERRED
P9.5 status                                  = DEFERRED
Next phase                                   = CONTROLLED DECISION REQUIRED
```

No contribution formula, Human-effort authority, candidate persistence,
ranking, MM, labor cost, ledger, or P/L behavior is implied. A later phase
must begin with a source-backed scope and ownership audit. Any change to
evidence authority, autonomous profiles, privacy scopes, Project attribution,
or financial use requires its own controlled amendment and acceptance.

## 12. Final Decision

```text
P9-S01 THROUGH P9-S31 COMPLETE
P9-S31A PRIVACY CORRECTIVE CLOSURE PASS
P9-CA01 / CA02 / CA03 / CA04 PASS
P9 FOUNDATION CLOSED / REVALIDATED
PROTECTED POSTGRESQL E2E PASSED
CONTRACTS, FULL GATE, AND COVERAGE FLOORS PASSED
ZERO-RESIDUE CLOSURE PASSED
P9.5 DEFERRED
NEXT PHASE NOT IMPLICITLY AUTHORIZED
```
