# P6-CA02-S5 Worker Readiness and Default-Profile Activation

**Status:** COMPLETE
**Date:** 2026-10-16
**Predecessor:** P6-CA02-S4 Profile-Aware Backend Routing
**Next:** Post-CA02 closure review or P7 entry planning

## Purpose

This Slice activates `NSL_V01_IN_PROCESS` as the initial AE Agent Runtime
worker profile and couples capability advertisement to installed-package
readiness. A worker cannot start or advertise the in-process profile merely
because a backend object exists.

```text
installed nex-skill-language distribution
+ admission wheel lock
+ Platform Python dependency lock
+ exact public nsl.api surface
+ configured in-process backend
-> worker startup readiness PASS
-> capability profile advertisement
```

No RuntimeJob, binding, backend-run, result, lease, or database schema changed.

## Readiness Boundary

`inspect_installed_nsl_package()` verifies all of the following before the
in-process profile is admissible:

- distribution and package version match `nsl-v0.1-wheel.json`;
- the PEP 610 wheel origin filename and SHA-256 match the admitted wheel;
- the actual `python-production.lock` digest matches the admission lock;
- installed `cryptography` matches the locked version;
- `nsl.api` is loaded from the installed distribution, not a source checkout;
- every locked public API symbol is present; and
- source revision and admission lock lineage remain visible in readiness
  evidence.

Missing, malformed, or drifted evidence returns
`ae.agent_runtime_worker.nsl_package_unready`. The enabled worker does not
start and therefore cannot publish a misleading capability heartbeat.

## Default and Compatibility

Environment-loaded worker configuration now defaults to:

```text
NEX_AE_AGENT_WORKER_BACKEND_PROFILES=NSL_V01_IN_PROCESS
process_isolation_required=false
```

The builder infers process-isolation requirements from the selected profile
set. Explicit `NSL_V01_PROCESS_ISOLATED` and dual-profile workers still require
process isolation and remain valid compatibility configurations. Historical
durable rows are not rewritten and no implicit backend fallback was added.

The worker CLI `--check` automatically loads the configured admission lock and
validates the installed package. Tests and composed runtimes may inject the
same evidence explicitly to keep unit boundaries deterministic.

## Protected Evidence

The protected smoke used the actual package installed in `.venv`:

```text
distribution: nex-skill-language
package version: 0.1.0
source revision: 3b4cb198888570a857e6fb0d3aa077930bb23504
wheel sha256: 290a202f540ec98291842e9281a28288cc7ac112525b6c0f02c10b8721aef21f
cryptography: 46.0.7
default profile: NSL_V01_IN_PROCESS
checks: 8/8 PASS
```

The smoke also constructed the actual in-process adapter/router, passed worker
startup readiness, and independently confirmed the process-isolated
compatibility profile without in-process package evidence.

PostgreSQL and remote model providers were not required because this Slice
changes deployment admission and worker startup only.

## Regression and Coverage

Final NeX-AE Slice Gate:

```text
3,880 passed, 6 protected tests skipped
statement coverage: 98.61%
branch coverage: 96.83%
contract validation: PASS
schemas/examples/negative examples/OpenAPI: 174/236/204/7
protected installed-wheel smoke: 8/8 PASS
```

Focused new-boundary coverage:

```text
nsl_package_admission.py: 96.69% statement, 95.83% branch
S5 protected smoke: 98.25% statement, 100.00% branch
```

An initial combined file-module coverage invocation caused pytest collection
to import `nex_runtime` twice and triggered SQLAlchemy registry duplication.
The final evidence uses service-scoped AE coverage plus independent shared
runtime and smoke-file coverage, avoiding that instrumentation artifact.

The broad `nex-runtime` service profile remains below its global gate at
90.08% statement and 87.24% branch because it includes unrelated legacy shared
modules with little or no service-profile coverage. The modified admission
module itself exceeds both required thresholds as shown above.

## Boundary

- No database migration or PostgreSQL smoke was needed.
- No remote embedding, reranking, or generation provider was used.
- Process-isolated execution remains available but is no longer the initial
  default.
- Package readiness does not claim hard crash containment for in-process NSL.
- P6 identity, persistence, retry, replay, and result contracts remain intact.
