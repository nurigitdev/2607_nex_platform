# P9 Final As-Built Baseline and Next-Phase Handoff v1.0

**Status:** FINAL / P9 FOUNDATION CLOSED / P9-CA04 PASS

**Phase Closed:** P9 - NeX-WA Work Evidence and Work Asset Foundation

**Next Phase:** Not selected; controlled decision required

**Observed Date:** 2026-10-28

**Platform Branch:** `transition/p4-agent-runtime-foundation`

## 1. Purpose

This document freezes the source-backed P9 Foundation after P9-S01 through
P9-S31. It records the executable Git baseline, contracts, migrations,
installed topology, protected PostgreSQL evidence, reliability evidence, and
deferred scope without expanding Work Asset authority.

P9 closes NeX-WA as a post-work evidence service. It does not authorize a
scheduler, approval engine, Human-effort authority, payroll source, accounting
system, or Project profitability calculation.

## 2. Executable Baseline Identity

The accepted executable baseline is the P9-S30 closure:

```text
repository     = nurigitdev/2607_nex_platform
branch         = transition/p4-agent-runtime-foundation
commit         = bc28307a58b659c791211d995ea773c77ef786c0
tree           = 0b687578bb120e68b67f0f14bb5cab9f376496cf
contracts tree = 9fdf95175cbcaf22c13fca81009ccd26c69578e9
```

P9-S31 changes documentation and its consistency regression only. Its commit
is resolved from Git history to avoid embedding a self-referential hash. P9
entry for any later phase means the S31 commit or a verified descendant that
preserves this executable baseline.

## 3. Closed Foundation Scope

The closed source-backed path is:

```text
authoritative AE AgentResult / Artifact or WC WorkResult
-> signed reference-only WA intake
-> service-local PostgreSQL JobQueue
-> fenced evidence consumer
-> source projection re-verification
-> immutable WorkEvidence
-> bounded WorkAsset and PRIMARY/SUPPORTING binding
-> replay-safe read, reconciliation, correction, and operations surfaces
```

OA retains Human identity authority, AE retains Agent execution and Artifact
authority, WC retains WorkResult lineage authority, and EOS retains Project
and membership authority. WA stores admitted references, hashes,
classification, authority snapshots, and lineage only.

## 4. Contract Baseline

Canonical validation at P9-S30 passed:

```text
JSON schemas      = 226
positive examples = 290
negative examples = 244
OpenAPI documents = 10
contract tree     = 9fdf95175cbcaf22c13fca81009ccd26c69578e9
```

The negative matrix includes unsupported sources, hash and identity conflicts,
cross-tenant access, inactive Human authority, missing Project/Claim context,
IA Project spoofing, non-READY or mismatched Artifacts, WC lineage mismatch,
pre-ACK AgentResult, stale settlement, raw payload exposure, invalid caller
scope, and unknown autonomous authority profiles.

## 5. Migration and Database Inventory

Source and actual `_test` PostgreSQL migration inventories match exactly:

| Service | Database / role | Source / applied | Current head |
| --- | --- | ---: | --- |
| NeX-OA | `nex_oa_test` / `nex_oa_user` | 20 / 20 | `2517_oa_service_principal_wa` |
| NeX-AE API | `nex_ae_test` / `nex_ae_user` | 61 / 61 | `2514_ae_nsl_v02_profile` |
| NeX-CX | `nex_cx_test` / `nex_cx_user` | 23 / 23 | `1374_cx_trace_projection_indexes` |
| NeX-MO | `nex_mo_test` / `nex_mo_user` | 10 / 10 | `1470_mo_model_rollout_persistence` |
| NeX-AG | `nex_ag_test` / `nex_ag_user` | 20 / 20 | `1477_ag_platform_alert_persistence` |
| NeX-WC | `nex_wc_test` / `nex_wc_user` | 13 / 13 | `1006_wc_approval_foundation` |
| NeX-EOS | `nex_eos_test` / `nex_eos_user` | 16 / 16 | `2515_eos_worker_heartbeat` |
| NeX-WA | `nex_wa_test` / `nex_wa_user` | 8 / 8 | `2607_wa_service_logs` |

Total source and applied migrations are `171 / 171`. NeX-WA owns:

```text
schema_migrations
service_jobs
service_worker_heartbeats
service_operational_events
service_log_entries
wa_work_evidence
wa_work_asset
wa_work_asset_evidence
```

No cross-service foreign key, direct cross-service database read, second WA
queue, or Foundation contribution-candidate table was introduced.

## 6. Installed Service Topology

The current deployment catalog contains nine immutable artifacts and seventeen
process bindings:

```text
artifacts = OA, AE, CX, MO, AG, WC, EOS, WA runtimes + AE Web
APIs      = OA, MO, CX, AE, AG, WC, EOS, WA
web       = AE Web
workers   = AE artifact render, AE retention, AG remediation sync,
            AG dispatch, CX async generation, CX ingestion,
            CX remediation, WA evidence consumer
```

P9 adds `nex-wa-api` and `nex-wa-evidence-consumer`. The consumer is an active
installed `job_claiming` process, runs `python -m nex_wa.consumer_main`, and is
supervised by Compose with `restart: unless-stopped`.

Accepted WA image identity:

```text
image      = nex-platform-local/nex-wa-runtime:p9-s27
image ID   = sha256:8049b21cddf7bb761632966a9c449eb4b4c899e1baf0add19812f43cf9d56c2a
repo digest= nex-platform-local/nex-wa-runtime@sha256:8049b21cddf7bb761632966a9c449eb4b4c899e1baf0add19812f43cf9d56c2a
user       = 65532:65532
```

The image passed non-root, read-only filesystem, network-none entrypoint, and
packaged consumer checks. No registry push is claimed.

## 7. Protected E2E and Reliability Evidence

The final protected acceptance was rerun against the actual AE, WC, OA, EOS,
and WA test databases with OA-signed service trust:

```text
protected acceptance = 41 passed
P9-S29 canonical E2E = PASS
concurrent claims     = PASS
stale-worker fencing = PASS
crash-after-commit   = idempotent replay PASS
dead-letter/replay   = PASS
installed runtime    = PASS
signed service trust = PASS
```

Evidence identities:

```text
protected acceptance JUnit sha256 = ba3ba01702e7c349b2d49f4c20dcd5a8d5a88786a8c4a932dbf77c07c5e52599
P9-S29 Slice coverage sha256       = c87389eece8e1882ac487eb5502bbd7fc15c0359d83ffff68e12b04dad326f73
P9-S29 closure record sha256       = 0f8d4aa364effacb133559be111a995c56eecd94073cfc693eb32d89fcfe1fdf
P9-S29 executable test sha256      = dc58d4f5c9241a6e010e55be121200a57d04855e753e55dc5ef99f3667ec92c2
stale-worker test sha256           = 001c670ddc982235593b4147b5a9e89168570a4d2a8e4a75435674b7239f8422
crash/replay test sha256           = 93733329bac4ded6bb150db19335c5059a37a2debffc8f3039c329cf532c1f44
operator replay record sha256      = 9da5aeb6b8dff42d2e94179fefec2c4f05879173c901efc0d61634cee28b05e5
```

The JUnit and coverage reports are local ignored artifacts; their hashes bind
the accepted run without committing environment-specific report contents.

## 8. Full Gate and Coverage Evidence

P9-S30 completed the canonical Repository Full Gate:

```text
pytest              = 18,264 passed, 131 protected skips
statement coverage  = 96.01% (required 96.00%)
branch coverage     = 95.22% (required 94.00%)
AE Web Node tests   = 403 passed
contract validation = 226 / 290 / 244 / 10
exit code           = 0
```

```text
coverage JSON sha256       = 50fc8a9f87ac908ec409e8e1e07a6cc5953196ee4b0842fe5d2d19239250d176
Full Gate JUnit sha256     = 3ce56bc221467b09cfe4a04d9b93ca64879e0ffd4aebc5aad2d25096afb7e6b7
Checkpoint #3 JSON sha256 = 57c57cd51ef36701d1722163f0b3b8bd64e143fa60d0c7c8798c7f6d45db1741
P9-S31 Slice coverage sha256 = af4c1b8fe49fc0f90f3a937ded38df9d4e1ee5b540c6b6669c90635fa14f5bf6
```

Relative to P9-CA03, the suite added 94 passing tests and four explicit
protected skips. Statement and branch coverage changed by only `-0.02` and
`-0.05` percentage points respectively, with no unexplained discontinuity.
The final NeX-WA Slice Gate passed `318` tests with `12` protected skips,
statement coverage `97.30%`, and branch coverage `94.70%`.

## 9. Zero-Residue Evidence

The protected acceptance owns a unique `P9S29-*` tenant prefix. After the
final rerun, scoped residue queries returned:

```text
nex_wa_test  = 0
nex_ae_test  = 0
nex_wc_test  = 0
nex_oa_test  = 0
nex_eos_test = 0
```

The protected JUnit includes the executable cleanup assertions. No token,
database URL, raw source body, prompt, Artifact bytes, or private content is
present in this document or the sanitized Slice records.

## 10. Frozen P9 Invariants

1. WA is post-work evidence and is not the Work system of record.
2. WA is not a Scheduler.
3. WA does not read or mutate another service's database directly.
4. Ordinary evidence admission is not Approval and creates no Approval.
5. Evidence intake creates no WC Delegation and requires no WC Delegation.
6. P9 Foundation has no NSL runtime dependency.
7. Positive Agent evidence requires the authoritative completion/publication
   ACK barrier.
8. Source equivalence and semantic idempotency are independent of JobQueue
   delivery idempotency.
9. Stale-worker recovery fences the former lease owner's settlement authority.
10. Basic, detail, audit, and operations privacy scopes remain separate.
11. Human ownership never implies Human effort, contribution, salary, cost, or
    Project profitability.
12. Future autonomous authority profiles fail closed unless admitted by a
    controlled contract amendment.

## 11. P9.5 Disposition

```text
P9-C01 Candidate Contract / Method Registry = DEFERRED
P9-C02 Deterministic Candidate Calculation  = DEFERRED
P9-C03 Golden C Candidate Handoff            = DEFERRED
P9.5 status                                  = DEFERRED
```

No contribution formula, Human-effort estimate authority, candidate
persistence, ranking, MM, labor cost, ledger, or P/L behavior is implied by
P9 Foundation closure.

## 12. Next-Phase Handoff

P9 does not select or authorize its successor. A later phase must begin with a
source-backed scope and ownership audit and must preserve this As-Built record.
Any change to evidence authority, contribution candidates, Human effort,
autonomous profiles, privacy scopes, Project attribution, or financial use
requires an explicit controlled amendment and its own protected acceptance.

## 13. Final Decision

```text
P9-S01 THROUGH P9-S31 COMPLETE
P9-CA01 / CA02 / CA03 / CA04 PASS
P9 FOUNDATION CLOSED
PROTECTED POSTGRESQL E2E PASSED
FAULT / RECOVERY PASSED
INSTALLED RUNTIME PASSED
CONTRACTS AND FULL GATE PASSED
COVERAGE FLOORS PASSED
ZERO-RESIDUE CLOSURE PASSED
P9.5 DEFERRED
NEXT PHASE NOT IMPLICITLY AUTHORIZED
```
