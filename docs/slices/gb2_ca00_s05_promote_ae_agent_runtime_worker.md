# GB2-CA00-S05: Promote AE Agent Runtime Worker

## Scope

S05 promotes the NeX-AE Agent Runtime worker from the P8-DEMO installed
composition into a first-class current Platform process. The promoted process
uses the generic composition extracted in S03 and does not import
`nex_ae_api.demo_runtime`, P8 demo runtime modules, or smoke-test source.

This Slice adds no database migration, table, public business API, scheduler,
dispatcher, queue, or execution engine.

## Canonical Process

```text
process_id          = nex-ae-agent-runtime-worker
artifact_id         = nex-ae-runtime
module              = nex_ae_api.agent_runtime_process
capability          = job_claiming
database            = NeX-AE PostgreSQL
heartbeat           = service_worker_heartbeats
shutdown            = SIGINT / SIGTERM graceful stop
composition factory = build_installed_runtime_composition
```

The process readiness boundary fails closed unless all of the following are
available:

```text
AE database connection and exact migration inventory
required Agent Runtime tables
dispatcher and assignment source
worker profile
executor registry and configured executor kinds
configured backend profiles
required package readiness, when configured
```

`local_mock` is package/source admission only. Work claiming is allowed only
through the protected `test` profile in this Slice.

## Activation Boundary

S05 admits a bounded deterministic component profile:

```text
DETERMINISTIC_AGGREGATE
DETERMINISTIC_REPORT
NSL_V01_PROCESS_ISOLATED backend identity
```

This profile proves the installed dispatcher/worker/executor path without
claiming that finance, controlled Skill, or full NSL domain activation is
already canonical. Registry and domain activation remain owned by S09 and S10.

## Deployment Reconciliation

The current process manifest, deployment artifact binding, and packaged
entrypoint catalog now include the AE worker. The current topology is therefore
`9 artifacts / 18 installed processes`; the GB2 target remains `9 / 20` after
the later WC event-delivery and EOS outbox-publisher promotions.

The S01 machine-readable inventory now records:

```text
promotion targets       = 3
currently promoted      = nex-ae-agent-runtime-worker
remaining promotions    = 2
target process count    = 20
```

## Protected Component Evidence

The opt-in S05 smoke applies the current AE migrations to the actual
`nex_ae_test` database, verifies exact database and role identity, admits a
bounded existing deterministic plan, and executes it through the canonical
process.

The smoke verifies:

```text
dependency execution and successor scheduling
canonical worker claim, handler, and settlement
two distinct DONE jobs and DONE attempts
PostgreSQL worker heartbeat and STOPPED lifecycle
process reconstruction and restart
zero duplicate execution after restart
component-scoped cleanup and zero residue
```

Evidence classification is `PROTECTED_COMPONENT`; it is not Golden Journey
evidence. Remote embedding, reranking, and generation providers are not needed
for S05.

## Verification

```text
focused process and smoke tests        = 19 passed
inventory/topology focused regression = 34 passed
canonical process statement / branch  = 100.00% / 99%+
NeX-AE Slice Gate                     = 5,678 passed, 44 skipped
NeX-AE statement / branch             = 97.04% / 95.35%
Repository Checkpoint Gate #1         = 17,600 passed, 129 skipped
Repository statement / branch         = 98.18% / 96.64%
contract validation                   = 226 / 290 / 244 / 10
actual PostgreSQL component checks    = 19 / 19
executed jobs / attempts              = 2 / 2
remaining component rows              = 0
ruff / diff check                     = PASS
```

The first Checkpoint run exposed the stale S01 current-process count of 17.
The inventory contract was reconciled to the current 18-process state and the
complete Checkpoint Gate was rerun successfully.

## Exit

```text
AE Agent Runtime worker      = CURRENT PLATFORM PROCESS
generic composition reuse   = PASS
demo runtime dependency     = NONE
protected component smoke   = PASS
restart / no-double-execute = PASS
database migration          = NONE
Checkpoint Gate #1          = PASS
next slice                  = GB2-CA00-S06
```
