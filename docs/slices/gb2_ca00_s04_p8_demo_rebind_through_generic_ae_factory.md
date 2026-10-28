# GB2-CA00-S04: P8-DEMO Rebind Through Generic AE Factory

## Scope

S04 rebinds the historical P8-DEMO installed Agent Runtime through the generic
NeX-AE composition introduced by GB2-CA00-S03. It removes duplicate runtime
orchestration without changing database schemas, public APIs, RuntimeJob state,
WAIT/RESUME behavior, approval authority, or result-finalization semantics.

## Ownership After Rebind

The P8-DEMO adapter continues to own only domain and scenario configuration:

```text
P8DemoControlledSkillRuntime
Golden A fixture and base-fixture paths
admitted NSL bundle, wheel, lock, and Skill-root paths
OA/EOS demo service bindings
optional WA completion-notifier policy
historical P8-DEMO composition-mode projection
```

The generic `nex_ae_api.runtime_composition` module is now the sole owner of:

```text
RuntimeJob queue construction
MultiStepEngine construction and successor scheduling
dispatcher and assignment-source construction
P5 step worker and durable continuation source
bounded worker lifecycle execution
workspace result publisher and installed result closer
```

`p8_demo_runtime_composition.py` creates the P6 executor registry from its
controlled Skill, wraps it in a `RuntimeExecutorProfile`, and passes that
profile plus the demo resource and optional notifier to
`build_installed_runtime_composition()`. The compatibility wrapper delegates
`run_cycle()` to the generic composition and preserves the historical
`EXISTING_COMPONENT_COMPOSITION` evidence value.

## Compatibility

The following public compatibility names remain available:

```text
InstalledP8RuntimeComposition
InstalledP8StepAssignmentHandler
build_installed_p8_runtime_composition
```

Existing S10B installed runtime, S10C workspace/result closure, S11 Chairman
Golden Journey, AE runtime image, and S12 release-operation tests remain green.
The generic module retains zero imports from P8 demo, controlled-Skill, or demo
fixture modules.

## Verification

```text
adapter-focused tests                 = 15 passed
S03 + P8 historical focused set       = 91 passed
adapter statement / branch            = 100.00% / 100.00%
NeX-AE Slice Gate                     = 5,615 passed, 45 protected skips
NeX-AE statement / branch             = 97.03% / 95.35%
changed-module statement / branch     = 100.00% / 100.00%
contract validation                   = 226 / 290 / 244 / 10
ruff check / format                    = PASS
```

Protected PostgreSQL, RustFS, remote-provider, and Playwright tests remain
behind their existing explicit environment guards. S04 is a composition
ownership refactor and introduces no new persistence or live-provider boundary.

## Exit

```text
P8-DEMO behavior             = PRESERVED
P8-DEMO orchestration owner  = GENERIC AE FACTORY
P8-DEMO module role          = DOMAIN PROFILE / CONFIG WRAPPER
duplicate runtime assembly   = REMOVED
next slice                   = GB2-CA00-S05
```
