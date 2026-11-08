# NeX Platform v2.1 Transition Final As-Built and Master Merge Handoff v1.0

**Status:** FINAL / TRANSITION CLOSED / MASTER MERGE READY

**Date:** 2026-11-08

**Repository:** `nurigitdev/2607_nex_platform`

**Source Branch:** `transition/p4-agent-runtime-foundation`

**Target Branch:** `master`

**Target Baseline:** `ab7af0fc3b42225d1d71d20d517889d694a01c03` (`v1.0`)

## 1. Purpose

This record closes the long-running v2.1 transition branch at the accepted
Agent Runtime, Planning, NSL, Work Coordination, controlled WRITE, Work
Evidence, installed Platform, and calibrated retrieval baseline. It authorizes
integration into `master` while preserving the complete Slice history.

The merge is a baseline promotion. It does not claim that the deferred
Procurement, Inventory, or Manufacturing business expansion is complete.

## 2. Completed Scope

The transition branch includes the accepted implementation and evidence for:

```text
P4    Agent Runtime Foundation
P5    deterministic Planning and ExecutablePlan
P6    NSL runtime integration and dual runtime profiles
P6.5  live semantic intent/context/plan generation
P7    WC delegation, background execution, result delivery, and resume
P8    EOS, approvals, controlled WRITE, Golden A, and Project operations
P9    WA evidence, WorkAsset, privacy, restart, and installed worker runtime
GB2   smoke-to-product runtime internalization and installed Platform closure
S20A-J coverage ownership and active runtime branch hardening
S20K-R retrieval calibration, controlled activation, and deferred live replay
```

The accepted installed Platform contains nine owner-scoped OCI artifacts and
twenty current product processes. Installed workers, not smoke fixtures, own
runtime transitions.

## 3. Final Accepted Runtime Evidence

The latest executable baseline is `c53b3e3606f9178f4f60689c2330fbeec44871a5`.
Later transition commits record closure evidence only and do not relax runtime,
coverage, calibration, or admission policy.

```text
S20R protected live matrix       = 6 / 6 PASS
S20R acceptance checks           = 20 / 20 PASS
HOLDOUT accessed                 = false
HOLDOUT reexecuted               = false
threshold/profile changed        = false
owned runtime residue            = 0

Repository Full Gate             = PASS, exit 0
pytest                            = 20,351 passed / 133 protected skips
statement coverage                = 96.74% (required 96.00%)
branch coverage                   = 96.02% (required 94.00%)
product statement / branch        = 98.67% / 97.33%
harness statement / branch        = 94.18% / 92.97%
AE Web Node regression            = 404 passed
contracts                          = 230 schemas / 291 positive examples /
                                     245 negative examples / 10 OpenAPI
```

Current admitted provider identities are model-neutral runtime bindings:

```text
embedding  Qwen3-Embedding-4B  hf:5cf2132abc99cad020ac570b19d031efec650f2b
reranking  Qwen3-Reranker-4B   hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
generation Qwen3.5-9B          hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
```

No endpoint, credential, database URL, API key, token, raw prompt, or private
business payload is recorded in this handoff.

## 4. Intentionally Deferred Scope

The following Golden B v2 business expansion is intentionally deferred:

```text
Manufacturing risk/shortage authoritative source
Manufacturing readiness business capability and READ Skill
Procurement Child Work capability and result contract
Inventory and material business integration
Manufacturing-to-Procurement full Parent/Child journey
Golden B collaboration workbench and mandatory fault suite
```

These items are backlog, not defects in the accepted Platform foundation.
When work resumes, the first boundary is:

```text
GB2-CA01: Source-Backed Manufacturing Delegation Contract Closure
```

GB2-CA01 must resolve the canonical risk source, Procurement capability and
Skill identity, Child Result contract, WA projection, Work closure authority,
and optional CX/MO boundary before domain coding begins.

## 5. Merge Policy

The transition branch is a strict descendant of the `v1.0` `master` baseline.
At final review, `master` had no unique commit and the transition branch had
434 unique commits.

The pull request SHALL therefore use:

```text
base             = master
compare          = transition/p4-agent-runtime-foundation
merge method     = Create a merge commit
squash merge     = forbidden
rebase merge     = forbidden
```

The Slice-level commit history is part of the engineering evidence and must be
retained. The `v1.0` tag remains on its historical commit.

After merge, a non-release baseline tag such as
`v2.1-transition-baseline` or `v2.1-agent-runtime-foundation` may be created.
The plain `v2.1` release tag remains reserved until its release scope is
explicitly approved.

## 6. Post-Merge Verification

Because `master` is an ancestor of the transition branch, the merge commit
must introduce no tree change beyond the accepted transition tip. Verify:

```text
merge commit has two parents
merged tree equals the transition tip tree
working tree is clean
remote master points to the merge commit
v1.0 tag remains unchanged
no transition-owned Docker container or database residue remains
```

The accepted Full Gate need not be repeated solely because of the merge
commit when the tree identity is unchanged. Any merge-time code or contract
change invalidates that exemption and requires the applicable gates again.

## 7. Final Decision

```text
TRANSITION IMPLEMENTATION            = COMPLETE
CURRENT PLATFORM BASELINE             = ACCEPTED
S20R CALIBRATION/LIVE REPLAY           = CLOSED
PROCUREMENT/INVENTORY/MANUFACTURING    = INTENTIONALLY DEFERRED
MASTER MERGE                           = AUTHORIZED BY MERGE COMMIT
RESUME BOUNDARY                        = GB2-CA01
```
