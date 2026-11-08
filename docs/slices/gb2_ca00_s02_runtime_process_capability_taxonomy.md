# GB2-CA00-S02: Runtime Process Capability Taxonomy

## Scope

S02 extends the packaged runtime capability vocabulary so topology can
distinguish an executable domain-work loop from a lifecycle-only process.
It does not add a process, artifact, database migration, table, broker, or
public business API.

## Canonical Taxonomy

```text
request_serving       = API request handling; not background domain work
static_serving        = Web/static serving; not background domain work
job_claiming          = durable work claim and execution loop
event_delivering      = durable event delivery loop
outbox_publishing     = durable outbox publication loop
scheduled_maintenance = scheduled maintenance execution loop
lifecycle_only        = import/readiness/lifecycle shell; no domain work
```

The taxonomy is bounded and fail-closed. Unknown values are rejected, process
kind compatibility is checked, and a domain-work capability is accepted only
when the process ID has an explicit capability binding. Changing a
`lifecycle_only` definition to a known domain capability therefore does not
activate work.

## Promotion Readiness

The following future bindings are admitted as taxonomy metadata only:

```text
nex-ae-agent-runtime-worker  -> job_claiming
nex-wc-event-delivery-worker -> event_delivering
nex-eos-outbox-publisher     -> outbox_publishing
```

They remain absent from the current process manifest and artifact bindings.
S05, S06, and S07 respectively own their canonical entrypoint and process
promotion.

Current topology remains:

```text
artifacts           = 9
installed processes = 17
domain-work loops   = 2
  CX ingestion      = job_claiming
  WA evidence       = job_claiming
lifecycle-only      = 6
```

The historical 13-process manifest also remains compatible with one admitted
domain-work loop and six lifecycle-only backgrounds.

## Implementation

```text
services/_shared/nex_runtime/deployment_entrypoints.py
  bounded capability vocabulary
  explicit domain process bindings
  kind and process-binding validation
  domain_work_enabled projection
  per-capability and domain-work counts

services/_shared/nex_runtime/__init__.py
  public taxonomy contract exports

tests/test_nex_runtime_gb2_ca00_s02_capability_taxonomy.py
  known/unknown capability validation
  distinct worker capability validation
  lifecycle-only anti-escalation validation
  historical/current compatibility validation
```

## Verification

```text
focused regression                  = 17 passed
Platform Slice Gate                 = 387 passed, 6 protected skips
Slice statement / branch            = 99.26% / 98.28%
risk-escalated Checkpoint Gate       = 17,556 passed, 130 protected skips
Checkpoint statement / branch       = 98.17% / 96.62%
changed-module statement / branch   = 99.26% / 98.28%
contract validation                 = 226 / 290 / 244 / 10
git diff --check                    = PASS
```

The first Slice Gate scope included `nex_runtime/__init__.py` as a direct
coverage target. The gate runner converts that path to
`nex_runtime.__init__`, while Python imports the package as `nex_runtime`, so
the scope checker reported an absent module after all tests passed. The
accepted Gate scopes the executable `deployment_entrypoints.py` change;
`__init__.py` contains public re-exports only. No threshold was lowered and no
test failure was suppressed.

## Exit

```text
process capability model = READY FOR S03-S07
domain semantics         = UNCHANGED
current topology         = 9 artifacts / 17 processes
next slice               = GB2-CA00-S03
```
