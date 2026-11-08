# GB2-CA00-S16 Model Provider Admission and Readiness

## Status

```text
Slice                               = GB2-CA00-S16
Status                              = CLOSED
Canonical owner                     = NeX-MO
Database migration                  = NONE
Checkpoint Gate #3                  = PASS
Next Slice                          = GB2-CA00-S17
```

## Goal

Make model-provider readiness a declared Platform dependency rather than a
Golden Journey-owned preflight. A configured live mode alone must never admit
semantic planning.

## Canonical Boundary

NeX-MO now owns the canonical admission operation in:

```text
services/nex-mo/nex_mo/model_provider_admission.py
```

The operation reuses the existing source-backed boundaries:

```text
ProviderReadinessService
ProviderReadinessProbePlan
active remote-provider preflight
platform_dependency_readiness.v1
```

It does not add a second provider HTTP client, a second provider catalog, or a
new persistence table.

## Dependency Profiles

The profile is selected with `NEX_MO_PROVIDER_DEPENDENCY_PROFILE`.

| Profile | embedding | reranking | generation |
|---|---:|---:|---:|
| `rag` (default) | required | required | required |
| `semantic_planning` | optional | optional | required |

The default preserves current Platform and P8-DEMO continuity. The planning
profile permits generation-only readiness without falsely declaring the two
retrieval providers required.

## Admission Conditions

Every required capability must prove all of the following:

```text
configured
authorized by a successful bounded request
model/deployment/route identity admitted
active preflight request succeeded
timeout policy is bounded
validated response was observed
provider mode is admitted
```

Live timeout bounds are:

```text
embedding  = 10..300 seconds
reranking  = 10..300 seconds
generation = 30..300 seconds
```

Deterministic mock readiness remains available only when a caller explicitly
does not require live execution. `NEX_MO_PROVIDER_MODE=live` without successful
active admission produces `BLOCKED` and `NOT_READY`.

## Platform Readiness Projection

Each required capability is normalized to the S13 dependency contract:

```text
provider:embedding
provider:reranking
provider:generation
```

The owner is `nex-mo` and the dependency type is `MODEL_PROVIDER`. Optional
profile dependencies may be absent without making the aggregate not ready;
missing or blocked required dependencies fail closed.

## Legacy and Demo Compatibility

`run_dgx_live_provider_preflight.py` is now a compatibility wrapper over the
canonical admission operation. It no longer owns provider probing logic.

P8-DEMO external dependency admission additionally requires the canonical
projection to report:

```text
profile          = rag
admission_status = ADMITTED
readiness_status = READY
```

The older safe check list remains projected for existing protected-profile and
operator tooling.

## Privacy Boundary

Admission evidence includes model identity and bounded operational metadata,
but excludes:

```text
provider API keys
raw provider endpoints
preflight prompt content
raw provider responses
```

Unexpected configuration and admission failures are converted to bounded
failure codes without retaining exception detail.

## Protected Live Evidence

The canonical wrapper was executed against the actual DGX provider routes:

```text
generation  9111 = PASS
embedding   9112 = PASS
reranking   9113 = PASS
profile          = rag
admission        = ADMITTED
readiness        = READY
redaction        = PASS
```

Ignored local evidence is available at:

```text
reports/deployment/gb2-ca00-s16-model-provider-admission.json
reports/quality/gb2-ca00-s16-nex-mo.coverage.json
reports/quality/gb2-ca00-s16-checkpoint.coverage.json
```

## Verification

```text
focused S16/readiness regression       = 99 passed
provider surrounding regression        = 243 passed
NeX-MO Slice Gate                      = 1,307 passed / 6 skipped
NeX-MO statement / branch              = 99.80% / 99.40%
canonical module statement / branch    = 100.00% / 100.00%
DGX compatibility wrapper branch       = 100.00%
actual DGX protected admission          = PASS (3/3)
Checkpoint Gate #3                     = 17,849 passed / 131 skipped
Checkpoint statement / branch          = 98.23% / 96.68%
contract validation                    = 227 / 291 / 245 / 10
Golden Journey transition audit        = PASS
ruff / diff check                      = PASS
```

Checkpoint skips are existing explicit protected opt-in tests. S16's required
live provider acceptance was run separately against the actual DGX endpoints
and passed.

## Exit

```text
provider admission owner               = NeX-MO
live mode alone                        = INSUFFICIENT
generation provider readiness          = CANONICAL
retrieval provider requirement         = PROFILE-DEPENDENT
P8-DEMO direct preflight ownership      = REMOVED
CA00-DEPENDENCY-01                      = SATISFIED
next slice                             = GB2-CA00-S17
```
