# P6 Source Baseline Record v1.1

**Observed date:** 2026-10-14

## Platform

```text
Repository: nurigitdev/2607_nex_platform
Branch: transition/p4-agent-runtime-foundation
Current reviewed HEAD before P6-CA01 edits: 380efb339cb9e3119a32e9229cbcb5f0075d5f0f
P5 implementation closure commit: c9d4bccfecdf...
P5 JobQueue/RuntimeJob decision commit: e112606eedbd...
P6 v1.1 consolidation commit: 380efb339cb9...
```

## NSL

```text
Repository: nurigitdev/2608_nsl
Branch: master
Current reviewed source baseline:
803f22aadc3946a48b05472c80b60fe11d9d9554
Commit: ci: add NSL v0.1 quality gate
Tag: v0.1
```

## Codex Workspace Verification

Verified on 2026-10-14:

```text
Checkout path: /home/tprover/2608_nsl
HEAD: 803f22aadc3946a48b05472c80b60fe11d9d9554
Expected baseline match: yes
Working tree: clean
Checkout mode: detached HEAD at v0.1 / origin/master / master commit
```

The checkout path and detached/attached branch mode are environment evidence,
not product architecture requirements. The immutable commit SHA is the source
identity used by this baseline.

## Verified Source Inventory

The locally verified NSL v0.1 checkout contains source modules and As-Built
documents covering:

- READ execution semantics;
- package verification/signature;
- `SkillExecutionJob`;
- `SkillExecutionWorker`;
- stable `nsl.api` facade;
- process isolation;
- audit/snapshot/replay.

## Codex Source Availability Gate

The exact NSL checkout is now materialized and verified in the Codex workspace.
P6-CA01 refreshed the checkout SHA and working-tree state at closure time and
recorded an exact match with `803f22a...` in
`P6_CA01_Source_Backed_READ_Contract_Closure_v1.0.md`.

A path such as `/home/tprover/2608_nsl` is an environment detail, not a normative architecture path.

## Interpretation

```text
Executable NSL baseline = v0.1
Frozen target contract  = v0.2
P6 capability scope     = READ
```

## P6-CA01 Refresh Result

```text
Source availability gate: PASS
NSL baseline drift: none
Platform baseline recorded before CA01 edits: 380efb339cb9...
Golden signed READ package selected: yes
Process-isolated Golden execution: PASS
```
