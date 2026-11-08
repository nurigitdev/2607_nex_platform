# GB2-CA00-S03: Generic AE Installed Runtime Composition Extraction

## Scope

S03 extracts the reusable installed Agent Runtime composition from the P8 demo
module into the canonical NeX-AE service package. It does not change RuntimeJob,
MultiStepEngine, WAIT/RESUME, NSL approval, or result-publication state
semantics. It also does not change database schemas or public APIs.

## Canonical Boundary

`nex_ae_api.runtime_composition` now owns the installed runtime assembly for:

```text
SqlAlchemyRuntimeJobQueue
SqlAlchemyMultiStepEngine
SqlAlchemyAgentRuntimeDispatcher
SqlAlchemyAgentRuntimeAssignmentSource
SqlAlchemyNslApprovalResumeSource
P5StepExecutionWorker
AgentRuntimeWorkerLifecycle and bounded worker execution
SqlAlchemyWorkspaceResultPublisher
SqlAlchemyInstalledIaResultCloser
optional AgentResultCompletionNotifier
```

`RuntimeExecutorProfile` is the only domain execution boundary. A caller must
provide an admitted executor registry, an exact executor-to-backend mapping,
and optional installed package readiness. Missing profiles, empty registries,
partial backend mappings, malformed capability values, and malformed package
readiness fail closed before the runtime is assembled.

The generic module contains no Golden A, voucher, Chairman demo, P8 fixture,
demo Skill root, demo NSL bundle, or host-local path knowledge.

## Preserved Behavior

`InstalledStepAssignmentHandler` executes one claimed RuntimeJob through the
existing `P5StepExecutionWorker`. A non-WAITING result asks the existing
MultiStepEngine to schedule its durable successor; a WAITING result does not.

`InstalledRuntimeComposition.run_cycle()` preserves `claimed_count` as the
canonical execution count, invokes result finalization/publication after every
bounded cycle, combines worker and result-closure failures, and reports work
when either claim execution or result closure made progress.

## Deliberate Deferral

`p8_demo_runtime_composition.py` remains unchanged in S03. Rebinding it as a
thin demo profile over the generic factory belongs to GB2-CA00-S04. This keeps
the extraction independently reviewable and avoids mixing behavior migration
with the new canonical boundary.

## Verification

```text
focused tests                         = 21 passed
focused statement / branch            = 100.00% / 100.00%
NeX-AE Slice Gate                     = 5,612 passed, 45 protected skips
NeX-AE statement / branch             = 97.00% / 95.31%
changed-module statement / branch     = 100.00% / 100.00%
contract validation                   = 226 / 290 / 244 / 10
ruff check / format                    = PASS
generic demo-dependency source check  = PASS
```

Protected PostgreSQL, RustFS, remote-provider, and Playwright tests remained
disabled by their explicit environment guards. S03 changes composition only;
it does not introduce a persistence or live-provider boundary requiring a new
protected smoke.

## Exit

```text
generic installed AE composition = READY
demo/domain knowledge in generic  = NONE
historical P8 demo behavior       = UNCHANGED
next slice                        = GB2-CA00-S04
```
