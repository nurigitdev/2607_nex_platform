# P6-CA02-S7 Dual-Profile Parity and PostgreSQL E2E

**Status:** COMPLETE
**Date:** 2026-10-16
**Predecessor:** P6-CA02-S6 Timeout, Crash, and Lease-Recovery Hardening
**Next:** P6-CA02 closure / Full Gate decision

## Purpose

This Slice proves that the initial `NSL_V01_IN_PROCESS` profile and the
optional `NSL_V01_PROCESS_ISOLATED` compatibility profile preserve one AE
READ contract through the complete durable path:

```text
AgentExecution
-> ExecutablePlan / LOCAL_SKILL
-> RuntimeJob / capability-aware worker
-> VerifiedSkillArtifact
-> NSLStepExecutionBinding / SkillExecutionRequest
-> selected NSL READ backend
-> NSLResultSummary
-> StepResult v1.2
-> AgentResult / pending delivery
```

No schema or production runtime contract was added.

## Parity Rule

Each profile runs as an independent tenant-scoped PostgreSQL journey. Random
execution identities, timestamps, backend-run refs, and tenant-scoped opaque
artifact refs are not required to be byte-identical across the two journeys.
They must remain internally consistent from request through StepResult.

Cross-profile parity compares:

- the complete field sets and stable semantic projection of
  `SkillExecutionRequest`;
- Skill/package selectors, terminal status, completeness, resource summary,
  and result policy fields from `NSLResultSummary`;
- the NSL runtime result after removing only its execution UUID;
- StepResult v1.2 status, contract, executor, stable payload, and evidence/ref
  classes; and
- identical durable row cardinality, restart behavior, and cleanup behavior.

Opaque artifact refs are compared by class across tenants and are also
checked for exact binding -> summary -> StepResult lineage inside each
journey.

## Implementation

The existing P6-S7 IA READ E2E helper is now backend-profile aware. It:

- compiles the exact selected backend profile into the capability snapshot;
- constructs either the installed-wheel In-Process backend or the historical
  Process-Isolated backend;
- advertises the matching worker capability and supplies the admitted wheel
  readiness evidence for In-Process startup;
- captures bounded, content-free parity projections before cleanup; and
- retains the historical Process-Isolated P6-S7 smoke behavior.

The S7 protected runner executes both profiles in sequence and fails closed on
contract drift, profile fallback, incomplete evidence, dirty/unadmitted NSL
source, migration drift, or cleanup residue.

## Admission Correction

The first protected run exposed an obsolete P6-S5 source SHA embedded in the
historical P6-S7 smoke. The current clean NSL checkout was already the source
revision admitted by `deployment/locks/nsl-v0.1-wheel.json`:

```text
source revision: 3b4cb198888570a857e6fb0d3aa077930bb23504
wheel: nex_skill_language-0.1.0-py3-none-any.whl
wheel sha256: sha256:290a202f540ec98291842e9281a28288cc7ac112525b6c0f02c10b8721aef21f
```

S7 now reads the canonical admission lock instead of duplicating its revision.
It also stopped placing the source checkout on `sys.path`; fixture source is
read from the checkout, while Runtime imports must resolve from the admitted
installed wheel.

## PostgreSQL Evidence

The protected smoke connected directly to `nex_ae_test` as `nex_ae_user`,
confirmed migration `2205_ae_nsl_dual_profile`, and ran both complete E2E
journeys.

```text
status: PASS
checks: 10/10
parity dimensions: 5/5
actual PostgreSQL: true
profiles: NSL_V01_IN_PROCESS, NSL_V01_PROCESS_ISOLATED
rows per profile: 1 binding, 1 backend run, 2 StepResults, 1 AgentResult
cleanup residue per profile: 0
remote provider required: no
```

Both profile paths independently passed 24 internal E2E checks. The protected
failure tests also proved fail-closed cleanup when the dependent step,
StepResult evidence, or backend-run evidence is missing.

## Regression and Coverage

Final NeX-AE Slice Gate:

```text
3,905 passed, 5 protected tests skipped
statement coverage: 98.64%
branch coverage: 96.90%
S7 dual-profile runner: 100% statement, 100% branch
historical P6-S7 helper: 100% statement, 100% branch
contract validation: PASS
schemas/examples/negative examples/OpenAPI: 174/236/204/7
protected dual-profile PostgreSQL smoke: 10/10 PASS
commands: 5/5 PASS
```

The five skips require unrelated protected AE environments. Both explicitly
enabled P6-S7 PostgreSQL paths executed and were not skipped.

## Boundary

- No database table, column, or migration was added.
- RuntimeJob remains the AE execution source of record.
- `NSL_V01_IN_PROCESS` remains the initial profile.
- `NSL_V01_PROCESS_ISOLATED` remains an optional compatibility profile.
- Process isolation differences remain backend evidence, not business-result
  differences.
- Remote embedding, reranking, and generation providers were not required.
- The repository-wide Full Gate remains due at P6-CA02 closure or before P7.
