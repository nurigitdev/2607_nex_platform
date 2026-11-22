# W70-M1-PROMOTION-01: M1 Branch-to-Master Baseline Promotion

## Scope

This Slice promotes the accepted MyBee M1 branch to `master` without
squashing, rebasing, changing the accepted tree, or rerunning environment-heavy
evidence solely because of the merge commit.

The Git merge commit is the authoritative completion receipt. This document is
committed on the source branch before the merge so the promoted tree contains
the promotion policy and its regression guard without requiring a post-merge
documentation commit.

## Accepted Input

```text
repository              = nurigitdev/2607_nex_platform
source branch           = codex/mybee-phase1-implementation
preparation base        = 8b1009e0
product source          = 773769bafa2ac6680d3a775f81902a2e69103909
product source tree     = 823878f3a7fb90cfef96820398dbbb8a41ed9ef8
target branch           = master
target baseline         = 9fe6ddb1
remote divergence       = master 0 / source 251 before promotion preparation
```

The source branch was clean and synchronized with its remote. After a fresh
`git fetch origin`, `origin/master` remained `9fe6ddb1`, was an ancestor of
the source branch, and had no unique commit.

## Accepted Evidence

- M1 protected product journey: actual eight-service PostgreSQL, OpenBao,
  RustFS, live Qwen3.5-9B, authenticated Playwright, restart/replay, and zero
  residue, PASS.
- Exact-head Repository Full Gate: `24,031` Python tests, zero failures/errors,
  statement `96.3353%`, branch `95.3119%`.
- Product coverage: statement `98.2666%`, branch `96.7614%`.
- Canonical release: 9 non-root images, 18 Compose services, 21 processes,
  12 package/entrypoint checks, no registry push.
- Final As-Built regression: `4 passed`.
- MyBee Phase-1 regression: `806 passed`, `1` explicit protected skip.
- Contract validation: `274 / 320 / 260 / 10`, PASS.

## Merge Policy

The promotion must use:

```text
base          = master
compare       = codex/mybee-phase1-implementation
merge method  = Create a merge commit (--no-ff)
squash merge  = forbidden
rebase merge  = forbidden
```

The Slice-level commit history is engineering evidence and must remain in the
merge commit's second-parent ancestry.

## Post-Merge Acceptance

The promotion is complete only when all checks pass:

1. the merge commit has exactly two parents;
2. parent 1 is the fetched `origin/master` baseline;
3. parent 2 is the exact source-branch promotion tip;
4. the merge commit tree equals the source-branch tip tree;
5. `git diff source-tip..master` is empty;
6. the Final As-Built consistency regression passes on `master`;
7. canonical contract validation passes on `master`;
8. the working tree is clean;
9. `origin/master` points to the merge commit after push;
10. no tag is moved and no registry image is pushed.

The canonical Repository Full Gate does not need to be repeated when the merge
tree is byte-identical to the already accepted source tip.
Any merge-time tree change invalidates that exemption and requires the
applicable Gate again.

## Handoff

After successful promotion, `master` is the canonical MyBee M1 development
baseline. M1 remains `M1_CHECKPOINT_ONLY`; M2 remains open. The next
implementation boundary is `W80-CA01: M1-to-M2 Journal Lifecycle Entry
Reconciliation`, not direct destructive Journal mutation and not an implicit
claim that S5-01 through S5-04 are complete.

```text
PROMOTION METHOD       = MERGE COMMIT
SLICE HISTORY          = PRESERVED
TREE CHANGE AT MERGE   = FORBIDDEN
MASTER BASELINE        = MYBEE M1 AFTER ACCEPTED MERGE
NEXT BOUNDARY          = W80-CA01
```
