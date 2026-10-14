# P6-S4 LOCAL_SKILL Executor Activation

**Status:** COMPLETE
**Date:** 2026-10-15
**Predecessor:** P6-S3 NSLStepExecutionBinding and SkillExecutionRequest
**Next:** P6-S5 NSL READ Backend Integration

## Purpose

P6-S4 makes an exact, verified local Skill a runnable AE plan shape without
invoking the NSL runtime yet.

```text
P6 capability snapshot 1.2
-> deterministic compiler 1.2
-> ExecutableStep(LOCAL_SKILL)
-> dependency-complete executor registry
-> capability-aware worker startup ready
```

Historical P5 snapshot and plan schema 1.1 behavior remains unchanged.

## Source and Refactoring Audit

The existing ownership boundaries remain suitable:

- `planning_capabilities.py` owns exact capability selection;
- `executable_plans.py` owns deterministic plan compilation;
- `step_executors.py` owns executor registration and invocation;
- `agent_runtime_worker.py` owns startup capability validation; and
- P6-S2/S3 retain verified artifact and durable binding authority.

No new queue, table, broad package move, or direct Plan-to-NSL path was
introduced. The activation is an additive P6 contract over the existing P5
runtime.

## Activation Contract

An admitted local Skill descriptor binds all of the following exactly:

- Skill ID and exact version;
- Skill semantic hash;
- input, output, and runtime contract references;
- trust policy;
- `SIGNED_TRUSTED_ACTIVE` package requirement; and
- `NSL_V01_PROCESS_ISOLATED` backend profile.

Only a snapshot containing `LOCAL_SKILL` uses schema 1.2. Its compiled plan
uses schema 1.2/compiler `p6.1`, and the local step persists the exact
`skill_binding_json`. P5-only snapshots continue to produce schema 1.1 plans.

## Fail-Closed Composition

`LOCAL_SKILL` is registered only through `P6LocalSkillExecutor` and only when
all five dependencies are available:

1. verified Skill Artifact Gateway;
2. durable NSLStepExecutionBinding repository;
3. SkillExecutionRequest builder;
4. explicitly selected backend with the exact supported profile; and
5. result mapper.

Raw registry injection, unsupported backend profiles, missing methods,
non-callable dependencies, runtime binding drift, and invalid handler outcomes
all fail closed. The resulting registry exports its executor kinds and backend
profiles directly to the worker startup check, so configured support cannot
diverge from the composed runtime.

The injected handler is only the S4 activation boundary. P6-S5 owns artifact
resolution, binding/request orchestration, process-isolated NSL READ execution,
and result mapping. S4 therefore performs no NSL process or remote provider
call.

## Persistence

Migration `2203_ae_local_skill_activation` is additive and introduces no new
table. It:

- permits capability snapshot and executable plan schema 1.1 or 1.2;
- adds nullable `skill_binding_json` to `ae_executable_step`;
- admits `LOCAL_SKILL` as a step/executor kind; and
- requires an object binding only for a local Skill step and null otherwise.

Constraint names remain short and service-local. Existing 1.1 rows remain
readable and writable.

## Verification

Focused activation and adjacent compiler/binding regression:

```text
129 passed
executable_plans.py: 100% statement/branch coverage
nsl_step_executions.py: 100% statement/branch coverage
```

Actual `nex_ae_test` protected PostgreSQL smoke:

```text
database: nex_ae_test
role: nex_ae_user
42 migrations current
latest migration: 2203_ae_local_skill_activation
checks: 19/19 PASS
persisted executable steps: 2
persisted LOCAL_SKILL steps: 1
remaining smoke rows after cleanup: 0
```

The smoke proves schema 1.2 snapshot/plan persistence, deterministic lineage,
idempotent reload, dependency-complete startup, missing-dependency rejection,
private-prompt absence, no backend invocation, and zero residue.

Final AE Slice Gate:

```text
3714 passed, 5 protected opt-in tests skipped
statement coverage: 98.68%
branch coverage: 96.98%
contract validation: PASS
PostgreSQL smoke: 19/19 PASS
```

Generation, embedding, reranking, and the NSL runtime process are not required
for this Slice.
