# P8-DEMO-S10B: Installed P6-P8 Runtime Composition Extraction

## Outcome

The Chairman Demo AE runtime now composes the P6-P8 implementation that was
already present in the repository. This Slice adds no replacement business
workflow and no reduced read-only path.

```text
composition_mode           = EXISTING_COMPONENT_COMPOSITION
new_business_behavior      = false
dispatcher                 = existing DB-protected tenant dispatcher
worker                     = existing bounded Agent Runtime worker
executor registry          = existing P5/P6 executor registry
controlled WRITE target    = existing EOS adapter
```

## Installed Runtime Path

The installed path is now continuous:

```text
COMPILED
-> SqlAlchemyMultiStepEngine.schedule_next()
-> START_EXECUTION RuntimeJob
-> capability-aware dispatcher assignment
-> P5StepExecutionWorker / LOCAL_SKILL executor
-> admitted NSL Skill prefix
-> durable approval request + wait + checkpoint
-> WC decision event
-> RESUME_EXECUTION RuntimeJob
-> admitted controlled WRITE
-> EOS BusinessOperation / voucher commit
-> AE idempotency and write evidence
-> AgentExecution RESULT_VERIFY
```

`START_EXECUTION` and `RESULT_VERIFY` are the existing canonical P5 state
machine values. The Slice does not introduce a second scheduler, dispatcher,
worker, or executor registry.

## Package Boundary

The AE runtime image contains the exact admitted artifacts:

```text
NSL distribution          = nex-skill-language 0.2.1
wheel sha256              = a89ce5fde1a32749565ba0906a2f1faf1d440ff6db2dfc07c0b2a581378507cb
Skill ID                  = FINANCE.VOUCHER_DRAFT_CREATE
Skill version             = 1.1.0
Skill semantic hash       = sha256:b6ba60f6ae681dc754b6d304fcf7c99794a48e88429c698afd9d12afcb90a8fc
```

The exact-wheel implementation details are isolated in the shared installed
NSL adapter. Service-owned AE runtime source continues to avoid private NSL
module imports and consumes the admitted public API plus the bounded adapter
contract. Bundle admission time is immutable manifest data, so restart does
not change artifact identity.

Migration `2514_ae_nsl_v02_profile.sql` admits the v0.2 in-process backend in
the existing step-profile constraint. It does not rewrite persisted rows or
add a second persistence model.

## OCI Evidence

The final image was built from the current owner-scoped AE source context and
was not pushed to a registry.

```text
image                     = nex-platform-demo/nex-ae-runtime:p8-demo-s10b
image ID                  = sha256:b215b8b3587a0c419c624d529bb1413e22c7c58f63d66856ddefd9a88606d764
source context digest     = sha256:95dfa5ec55aebcf4542b0968fc806210c9e25bb7db575e1d9cb622fff71abb99
runtime user              = 65532:65532
package entrypoint check  = PASS
registry push             = false
```

The package check reports `P6_P8_EXISTING_COMPONENTS`, the existing
`SqlAlchemyAgentRuntimeAssignmentSource`, and `run_bounded_agent_runtime_worker`.
Domain claiming remains fail-closed until the P8-DEMO-S10 activation profile
is supplied.

## Protected Evidence

The protected smoke used the actual test databases and in-memory OA RSA
signing authority. No mock service token was admitted.

```text
AE database               = nex_ae_user@nex_ae_test
WC database               = nex_wc_user@nex_wc_test
EOS database              = nex_eos_user@nex_eos_test
OA database               = nex_oa_user@nex_oa_test
token rollout             = SIGNED_ONLY on AE/WC/EOS/OA
accepted mock tokens      = 0
checks                    = 10/10 PASS
approval checkpoint       = 1
EOS voucher / lines       = 1 / 2
EOS BusinessOperation     = 1
AE idempotency evidence   = 1
AE write evidence         = 1
```

Evidence is recorded in:

- `reports/deployment/p8-demo-s10b-installed-runtime.json`
- `reports/deployment/p8-demo-ae-runtime-image.json`
- `reports/quality/p8-demo-s10b-slice.coverage.json`

## Regression

```text
changed-test regression   = 326 passed
Slice Gate                = 5,555 passed / 44 protected skips
statement coverage        = 97.54%
branch coverage           = 95.94%
contract validation       = PASS (207 schemas / 271 examples / 231 negative examples / 9 OpenAPI)
```

The first Slice Gate exposed two real baseline drifts. The NSL private-module
dependency was moved out of AE service runtime into the exact-wheel adapter,
and the historical P7 resilience fixture now derives missing wait columns from
the current schema inventory. The gate then passed without lowering coverage
or contract thresholds.

## Closure

P8-DEMO-S10B is complete. P8-DEMO-S10 may activate the installed domain path
using this composition; it must not implement a parallel read-only AE runtime.
