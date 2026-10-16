# P6-CA02-S8 Runtime-Profile Acceptance and P7 Entry Closure

**Status:** COMPLETE
**Date:** 2026-10-16
**Predecessor:** P6-CA02-S7 Dual-Profile Parity and PostgreSQL E2E
**Next:** P7 planning and implementation

## Purpose

This Slice closes P6-CA02 by proving that the admitted in-process NSL runtime
profile is ready to become the P7 baseline without removing the historical
process-isolated compatibility profile.

```text
AE Runtime Worker
-> NSL_V01_IN_PROCESS by default
-> stable NSLReadBackend contract
-> existing request, identity, persistence, and result lineage

NSL_V01_PROCESS_ISOLATED
-> optional compatibility profile
-> no implicit fallback or contract fork
```

No database migration or remote model provider is part of this closure.

## Acceptance Runner

`scripts/smoke/run_p6_ca02_s8_runtime_profile_acceptance.py` composes the
authoritative S5, S6, and S7 evidence and fails closed unless all 12 closure
checks pass. It verifies:

- P6-CA02-S1 through S7 evidence is present;
- the canonical default is `NSL_V01_IN_PROCESS`;
- `NSL_V01_PROCESS_ISOLATED` remains optional and executable;
- unknown profiles fail closed;
- AE Runtime imports only the admitted `nsl.api` and
  `nsl.process_isolation` boundaries;
- installed-wheel and worker readiness pass;
- timeout, crash, stale-lease rejection, and lease recovery pass on actual
  PostgreSQL;
- both profiles complete the durable IA READ path on actual PostgreSQL;
- request, runtime result, result summary, StepResult v1.2, and identity
  lineage preserve parity; and
- both profile journeys leave zero database residue.

The runner is protected by `NEX_AE_P6_CA02_S8_ACCEPTANCE=1` and is the final
command in the repository Full Gate.

## Runtime Acceptance Evidence

The protected runner connected directly to `nex_ae_test` and passed:

```text
S8 closure checks: 12/12
installed-wheel readiness: 8/8
timeout/crash/lease recovery: 19/19
dual-profile PostgreSQL E2E: 10/10
cross-profile parity dimensions: 5/5
cleanup residue: 0 for both profiles
P7 default profile: NSL_V01_IN_PROCESS
optional profile: NSL_V01_PROCESS_ISOLATED
remote provider required: no
```

The two PostgreSQL journeys each persisted and then cleaned the complete
AgentExecution, RuntimeJob, NSL binding/backend run, StepResult, AgentResult,
dispatcher lease, and worker-heartbeat lineage. The recovery journey proved
that an expired attempt cannot publish a stale result and that the reclaimed
attempt completes without fabricated backend evidence.

## NSL Source Gate

The authoritative NSL checkout remained clean at revision
`3b4cb198888570a857e6fb0d3aa077930bb23504`. Its own quality command passed:

```text
tests: 1,225 passed
statement coverage: 99.47%
branch coverage: 98.56%
performance gate: PASS
requirements: 322 IMPLEMENTED, 2 PARTIAL, 1 PLANNED
certification: CONDITIONAL
```

The conditional certification is the existing declared state for
`NSL-SEC-013`, `NSL-AE-004`, and `NSL-AE-008`; it is not a new P6-CA02
regression or a hidden acceptance skip.

## Platform Gates

The focused NeX-AE Slice Gate passed before the Full Gate:

```text
3,906 passed, 10 protected tests skipped
statement coverage: 98.62%
branch coverage: 96.84%
S8 runner coverage: 100% statement, 100% branch
contract validation: 174/236/204/7
commands: 5/5 PASS
```

The repository-wide Full Gate then passed:

```text
14,710 passed, 38 protected tests skipped
statement coverage: 97.26%
branch coverage: 96.71%
contract validation: 174 schemas, 236 examples,
                     204 negative examples, 7 OpenAPI documents
final protected S8 acceptance: 12/12 PASS on actual PostgreSQL
```

The protected skips belong to unrelated environments. S8 directly enabled
and executed the required S5 readiness, S6 PostgreSQL recovery, and S7
dual-profile PostgreSQL acceptance paths; none of those paths was skipped.

## Regression Correction

The first Full Gate found one stale S142 assertion that required exactly 52
Python lock packages. P6-CA02-S1 correctly admitted the NSL wheel, so the
current lock contains 53 packages and 1,274 hashes. The closure check now
validates inventory-derived integrity properties instead of pinning a stale
package count:

- both Python and Node lock inventories must be present;
- the Python inventory must remain substantial and every package must retain
  at least one hash;
- all four Node packages must retain integrity evidence; and
- the complete S142 closure must still pass.

The focused S142 regression passed, and the complete Full Gate rerun passed.

## Evidence Digests

```text
Full Gate log:
  sha256:4b9d39ea1a3f092b3d7be917f59bf5a24ea75ba5dbeb48e70608d307e7c55d83
Platform coverage JSON:
  sha256:e66c2d1b13a0d9f8b63a5d677df3c0b43906891bc31d0de0b1232017edba7247
Platform JUnit XML:
  sha256:804d22abef4c6152e0365d2a1322ad21914372390e51080ed5d7b4a3c2fdec16
S8 acceptance JSON:
  sha256:f893020e17dfe3a24b8b87ad8dd8934fc421357afa258ea3d83af9f4c2c4e2a1
NSL coverage JSON:
  sha256:7766c82fb36f383faa844e451e576d08afaed150fa797a8c106da2882c46c3b1
NSL certification JSON:
  sha256:9bc3cb6f32bb1a75c106ac279e6911e5b53ba808ff766e62f29dfce88a0514a3
```

## P7 Entry Decision

P7 entry is **ACCEPTED** with these non-negotiable boundaries:

- `NSL_V01_IN_PROCESS` is the initial runtime profile;
- `NSL_V01_PROCESS_ISOLATED` remains an explicit optional compatibility
  profile;
- no unknown or unavailable profile may fall back silently;
- both profiles continue to share `NSLReadBackend`, identity, persistence,
  result, and timeline contracts;
- RuntimeJob remains the AE execution source of record;
- the admitted installed wheel and worker readiness remain startup gates;
- private NSL internals remain outside the AE Runtime dependency boundary;
  and
- future P7 behavior must add capability through the existing contract rather
  than fork profile-specific business semantics.
