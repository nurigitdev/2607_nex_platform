# GB2-CA00 Final As-Built and Golden B v2 Entry Handoff v1.0

**Status:** FINAL / GB2-CA00 CLOSED / GOLDEN B v2 AUTHORIZED

**Program:** NeX Platform v2.1

**Closed Gate:** GB2-CA00 Platform Runtime Internalization and Smoke-to-Product Promotion

**Successor:** Golden B v2 Manufacturing Delegation Full Journey

**Observed Date:** 2026-10-29

**Platform Branch:** `transition/p4-agent-runtime-foundation`

## 1. Purpose

This record freezes the executable Platform baseline produced by GB2-CA00 and
authorizes Golden B v2 business implementation. It proves that the current
installed Platform, rather than a smoke fixture, owns the runtime transition
from an authenticated request to durable work, controlled WRITE, publication,
and a user-visible result.

The governing rule remains:

> Smoke proves that the Platform works; smoke does not make the Platform work.

## 2. Exact Executable Baseline

```text
repository          = nurigitdev/2607_nex_platform
branch              = transition/p4-agent-runtime-foundation
executable commit   = ee91420f4949a12e72bd46bb01dfe5836b4428b0
executable tree     = b91e3960bb9343c4849e1521cde159981f177b81
OCI release digest  = sha256:fcf397856e3dff0a4c9becb4e74c43fca9c5a2e2813bc270720d383f04cd94ea
AE product image    = sha256:45d0a123e0ab69d8dfce787b2ae8ae8c867d455d6c246b2709c28a057e9da87e
NSL wheel sha256    = a89ce5fde1a32749565ba0906a2f1faf1d440ff6db2dfc07c0b2a581378507cb
registry push       = NOT PERFORMED
```

The Final As-Built document is a documentation-only descendant of this exact
runtime baseline. A later executable descendant is admissible only when it
preserves every invariant and re-runs the applicable gates.

## 3. Installed Topology

The accepted release set contains exactly nine owner-scoped artifacts:

| Artifact | Owner |
|---|---|
| `nex-oa-runtime` | NeX-OA |
| `nex-ae-runtime` | NeX-AE |
| `nex-cx-runtime` | NeX-CX |
| `nex-mo-runtime` | NeX-MO |
| `nex-ag-runtime` | NeX-AG |
| `nex-wc-runtime` | NeX-WC |
| `nex-eos-runtime` | NeX-EOS |
| `nex-wa-runtime` | NeX-WA |
| `nex-ae-web` | NeX-AE Web |

The current process manifest contains exactly twenty processes:

```text
APIs/Web (9)
nex-oa-api
nex-mo-api
nex-cx-api
nex-ae-api
nex-ag-api
nex-wc-api
nex-eos-api
nex-wa-api
nex-ae-web

Workers/Daemons (11)
nex-ae-artifact-render-worker
nex-ae-retention-daemon
nex-ag-remediation-sync-worker
nex-ag-dispatch-daemon
nex-cx-async-generation-worker
nex-cx-ingestion-worker
nex-cx-remediation-worker
nex-wa-evidence-consumer
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

The three GB2-promoted canonical business-process entrypoints are:

```text
python -m nex_ae_api.agent_runtime_process --profile staging_live
python -m nex_wc.event_delivery_process --profile staging_live
python -m nex_eos.outbox_publisher_process --profile staging_live
```

The packaged process manifest retains `local_mock` as its portable package
check default; installed Compose overrides only the profile to `staging_live`
without replacing these product modules. Historical `demo_runtime` and
`NEX_AE_DEMO_*` inputs are not active deployment dependencies.

## 4. Canonical Runtime Composition

`nex_ae_api.runtime_composition` is the generic installed AE runtime factory.
It assembles the durable RuntimeJob queue, dispatcher, assignment source,
MultiStepEngine, approval resume source, executor profile, result publisher,
and IA result closer without Golden A, voucher, P8 fixture, or host-local
business knowledge.

`nex_ae_api.agent_runtime_process` is the installed long-running process. A
bounded component run may finalize its own worker lifecycle, while daemon
cycles keep the heartbeat live and emit `STOPPED` only at process shutdown.
This distinction was discovered and closed by the final installed acceptance.

## 5. Domain Activation and Golden A Registration

The product boundary is split deliberately:

```text
DomainIntentActivatorRegistry
  -> deterministic capability-to-activator selection

ProductCapabilityRegistry
  -> exact capability, LOCAL_SKILL, bundle, Skill version, and semantic hash

GoldenAFinanceAuthoritySource
  -> tenant-scoped business authority and protected scenario input
```

Golden A is registered as:

```text
Capability = FINANCE.CREATE_VOUCHER_DRAFT
Skill      = FINANCE.VOUCHER_DRAFT_CREATE
Version    = 1.1.0
```

Demo business fixtures are allowed only for pre-request database seed. The
installed worker resolves execution input from the Product Capability
Registry, admitted NSL artifact, AE PostgreSQL, OA, WC, and EOS authorities.

## 6. Testing Contract

The canonical contract is
`docs/testing/Golden_Journey_Platform_Integration_Testing_Contract_v1.0.md`.
After public request admission, a Golden Journey runner may poll, assert,
restart declared processes, and clean up; it may not create or settle runtime
transitions directly.

The registry and static audit reject unregistered Journey runners, forbidden
transition imports or calls, transition-table mutation, stale entries, and
missing evidence metadata. The audit is mandatory in Slice, Checkpoint, and
Full Gate paths.

P8-DEMO remains a compatibility and historical acceptance surface. The
Demo-to-Product dependency audit passed with all seven canonical edges, and
the historical S10/S10B/S10C/S11 regressions remain compatible. The current
S18 runner is the sole transition-enforced installed Golden Journey owner.

## 7. Dependency Readiness

The shared `platform_dependency_readiness.v1` contract is secret-free and
fail-closed. Owner adapters remain authoritative:

| Dependency | Canonical owner/boundary | Accepted state |
|---|---|---|
| OpenBao | deployment provisioning plus owner runtime resolution | READY |
| RustFS/S3 | owner bucket lifecycle, IAM, readback, and cross-owner denial | READY |
| Model provider | NeX-MO provider admission and active preflight | READY |

Configured is not equivalent to ready. Any missing required dependency,
authorization failure, route/model identity drift, or unknown required domain
activator blocks the relevant runtime path.

## 8. Final Acceptance Evidence

### OCI and Package Admission

```text
exact source revision          = ee91420f4949a12e72bd46bb01dfe5836b4428b0
release artifacts              = 9 / 9
non-root images                = 9 / 9
background/package checks      = 11 / 11
complete release set           = PASS
AE NSL product image           = PASS
secret included                = false
registry push                  = false
```

### S18 Installed Current-Platform Continuity

```text
actual dev PostgreSQL          = PASS (7 services, migrations current)
actual Docker Compose          = PASS (20 current processes)
actual OpenBao                 = PASS
actual RustFS                  = PASS
actual remote generation       = PASS (Qwen3.5-4B)
authenticated Playwright       = PASS
restart/recovery               = PASS
queue state before/after       = 0 / 0 / 0
runtime transition fixture     = false
manual domain transition       = false
```

### S19 Negative and Restart Matrix

```text
N01 through N09                = 9 / 9 PASS
actual AE/WC/EOS test DBs      = PASS
pending-state restart recovery = PASS
duplicate settlement denied   = PASS
missing dependencies blocked  = PASS
unknown activator blocked      = PASS
forbidden fixture detected     = PASS
owned PostgreSQL residue       = 0
```

## 9. Final Repository Full Gate

```text
pytest                         = 18,693 passed / 133 protected skips
warnings                       = 1,607
statement coverage             = 96.02% (required 96.00%)
branch coverage                = 95.14% (required 94.00%)
JSON schemas                   = 227
positive examples              = 291
negative examples              = 245
OpenAPI documents              = 10
contracts                      = PASS
Golden Journey audit           = PASS
Demo-to-Product audit          = PASS
AE Web Node regression         = 404 / 404 PASS
Full Gate exit code            = 0
git diff --check               = PASS
```

Compared with the GB2 entry baseline (`18,268 / 131`, `96.01 / 95.22`), the
final baseline adds 425 passing tests and two explicitly protected skips.
Statement coverage increased by 0.01 percentage point. Branch coverage moved
by -0.08 percentage point while retaining a 1.14-point margin above the
required floor. The delta comes from the S01-S20 runtime, deployment,
dependency, and protected orchestration paths plus their regression tests; no
coverage threshold or source exclusion was relaxed.

## 10. Final Defects Closed During S20

The exact installed rerun exposed and closed three source-backed gaps:

1. The AE worker Compose owner lacked its WA service-token reference. The
   canonical owner environment now materializes `NEX_AE_TO_WA_SERVICE_TOKEN`.
2. A one-cycle worker emitted `STOPPED` after every daemon poll. Bounded
   lifecycle finalization is now explicit, and the daemon emits final STOPPED
   only once at process termination.
3. Canonical trust admission errors were sanitized so aggressively that a
   safe reason was hidden. Typed canonical trust failures now expose bounded
   diagnostic detail while arbitrary exceptions remain redacted.

The initial final-evidence image set was also stale relative to the source.
All nine images and the AE NSL product image were rebuilt from the exact
executable commit before the protected reruns.

## 11. Evidence Identities

The generated report files remain local ignored artifacts. Their hashes bind
this record to the accepted executions without committing environment values.

```text
OCI release report sha256       = e63e2630e4199b3c4aee5b0abecd9220598a61c0b4a1c56691cb7c36a23363b6
AE image report sha256          = bb71dfb4232ffb34a951d25eab9cf704560903a3d215421a5574afd0b400be98
S18 protected report sha256     = b7d9c5654566b3f669b5f04c4c0dd3cf645fac5d5846ec83d91ccee1feb7ef9c
S19 protected report sha256     = 9143febf3aaf4eb353ec19cc84a4cd7f878df99a6936c75116bf9d1a5754be59
Full Gate coverage sha256       = 4edc19d4965151c2e82350a2d7aa521d7a53bf14af36e4119f145fd9637ee214
Full Gate JUnit sha256          = 2334ea08b51f4b192b1aafe7f35c5766cefe9ff9a3e9f57521850e336b74c652
```

No report contains a database URL, password, service token, API key, raw
secret, or private business payload.

## 12. Frozen Invariants

1. Installed product processes, not smoke code, own runtime transitions.
2. The AE installed runtime factory remains domain-neutral.
3. Domain activation and exact Skill admission remain separate fail-closed
   registries.
4. Business fixtures are pre-request seed only and never worker input.
5. OA, AE, WC, EOS, WA, and each owner database retain service ownership.
6. OpenBao, object storage, and model-provider readiness remain owner-backed.
7. Golden Journey runners do not schedule, approve, write, publish, or ACK
   business state directly.
8. Restart and replay cannot duplicate AgentResult, delivery, BusinessOperation,
   Voucher, or outbox settlement.
9. P8-DEMO compatibility may wrap canonical product boundaries but may not be
   imported by product-owned runtime modules.
10. A required installed link that is missing or stale fails visibly.

## 13. Golden B v2 Entry Boundary

Golden B v2 is authorized to implement only the manufacturing business path:

```text
manufacturing evidence source
Manufacturing business capability
PA planning profile
manufacturing READ path
Manufacturing Readiness Artifact
IA -> WC -> PA business journey
WA evidence verification
```

Golden B v2 must reuse the installed worker topology, generic AE composition,
domain activator registry, product capability registration, dependency
readiness, testing contract, and protected acceptance machinery frozen here.
It must not reopen Platform wiring through a manufacturing-specific smoke
fixture.

## 14. Final Decision

```text
GB2-CA00 S01 THROUGH S20                 = COMPLETE
9-ARTIFACT / 20-PROCESS TOPOLOGY         = CLOSED
GENERIC AE RUNTIME AND PRODUCT WORKERS    = ACTIVE
DOMAIN ACTIVATION AND GOLDEN A REGISTRY   = ACTIVE
DEPENDENCY READINESS                      = READY / FAIL-CLOSED
P8-DEMO COMPATIBILITY                     = PASS
PROTECTED INSTALLED E2E                   = PASS
NEGATIVE / RESTART ACCEPTANCE             = PASS
REPOSITORY FULL GATE                      = PASS
ZERO OWNED RESIDUE                        = PASS
GB2-CA00                                  = CLOSED
GOLDEN B v2 IMPLEMENTATION                = AUTHORIZED
```
