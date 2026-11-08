# P6-S5 NSL READ Backend Integration

**Status:** COMPLETE
**Date:** 2026-10-15
**Predecessor:** P6-S4 LOCAL_SKILL Executor Activation
**Next:** P6-S6 Result and Timeline Integration

## Purpose

P6-S5 invokes the exact NSL v0.1 READ runtime without weakening the P6
identity, trust or process-isolation contracts.

```text
durable NSLStepExecutionBinding
-> exact VerifiedSkillArtifact
-> bounded SkillExecutionRequest + ContextProjection
-> NSLReadBackend(V01ReadBackendAdapter)
-> process-isolated SkillExecutionWorker
-> terminal RuntimeResultEnvelope
-> ordered progress + evidence bridge
-> immutable backend attempt evidence
```

P6-S6 remains the sole owner of `NSLResultSummary`, `StepExecutionOutcome`,
`StepResult v1.2` and timeline projection.

## Source Audit

The exact clean NSL checkout at `/home/tprover/2608_nsl` was verified at:

```text
803f22aadc3946a48b05472c80b60fe11d9d9554
```

The stable child boundary uses `nsl.api.SkillExecutionJob`,
`SkillExecutionWorker`, `RuntimeResultEnvelope`, and progress contracts. The
selected process implementation remains an explicit v0.1 adapter detail; no
backend auto-detection was added.

Existing authorities remain unchanged:

- `ae_runtime_job` owns queue, lease and worker-attempt authority;
- `ae_nsl_step_execution` owns request and execution identity binding;
- `ae_nsl_artifact` owns admitted artifact metadata; and
- new `ae_nsl_backend_run` owns immutable backend evidence for one numbered
  attempt only.

## Implementation

`nsl_read_backends.py` adds:

- a version-neutral `NSLReadBackend` port;
- exact P6-to-v0.1 job mapping with bounded nested runtime context;
- `V01ProcessEntrypoint` over stable `nsl.api` types;
- explicit spawned-process backend composition;
- terminal envelope, progress and evidence validation;
- fail-closed timeout, crash, target and protocol evidence;
- immutable SQLAlchemy backend-run persistence; and
- restart-safe execution orchestration that moves the binding to `RUNNING`
  before invocation and reuses an existing attempt record.

Raw child exception text, private prompts, signing keys and package bytes are
not persisted. Corrupt child wire data becomes bounded `PROTOCOL_ERROR`
evidence rather than escaping the isolation boundary.

## Persistence

Migration `2204_ae_nsl_backend_run` adds one short-named table and indexes. A
composite FK binds every run to the exact tenant, executable step and NSL
execution identity. The first PostgreSQL execution exposed and corrected a
real DDL mismatch: existing `executable_step_id` is `TEXT`, so the new FK now
uses the authoritative type instead of assuming UUID storage.

## Verification

Focused S5 and adjacent P6 regression:

```text
91 passed
nsl_read_backends.py: 100% statement, 99% branch coverage
```

Complete P6-CA01 through P6-S5 regression after the final isolation assertion
hardening:

```text
193 passed
```

Actual `nex_ae_test` protected source-backed smoke:

```text
database: nex_ae_test
role: nex_ae_user
43 migrations current
latest migration: 2204_ae_nsl_backend_run
checks: 26/26 PASS
backend attempts: 1
ordered progress events: 4
evidence references: 26
real timeout isolated: PASS
real non-zero child crash isolated: PASS
remaining S5/P5 rows after cleanup: 0
```

The protected PostgreSQL smoke was repeated after removing an invalid
dependency on one exact child-process exit code; both consecutive runs passed
all `26/26` checks.

The smoke compiled and production-verified the signed golden
`FINANCE.PROJECT_BUDGET_CHECK@1.0.0` package, executed its deterministic READ,
reloaded the attempt after repository reconstruction, and proved that the
parent process and PostgreSQL session survived both fault cases. Remote model
providers were not required.

Final AE Slice Gate with the complete P6 regression set:

```text
3662 passed, 5 protected tests skipped
statement coverage: 98.68%
branch coverage: 96.99%
contract validation: PASS
```
