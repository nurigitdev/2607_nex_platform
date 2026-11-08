# GB2-CA00-S19 Fail-Closed / Restart / Hidden-Gap Acceptance

## Status

```text
Slice                               = GB2-CA00-S19
Status                              = CLOSED
Canonical owner                     = Platform
Database migration                  = NONE
Protected PostgreSQL smoke          = PASS
Platform Slice Gate                 = PASS
Next Slice                          = GB2-CA00-S20
```

## Scope

S19 proves that the promoted current-Platform runtime does not rely on a
happy-path-only smoke fixture. It introduces a canonical N01-N09 acceptance
matrix and reuses the product AE runtime worker, WC event-delivery worker, EOS
outbox publisher, dependency readiness contract, domain activator registry,
and Golden Journey transition audit.

No business API, database schema, migration, or alternate execution engine was
added.

## Canonical Matrix

The shared `nex_runtime.hidden_gap_acceptance` contract requires the exact nine
scenarios, exact signal inventory, canonical evidence hash, correct execution
class, non-empty component ownership, and metadata-only evidence.

```text
N01  AE pending job survives worker absence/restart; no false completion
N02  WC pending delivery survives denial/restart; no false resume
N03  EOS pending outbox survives denial/restart; no duplicate transaction
N04  missing required OpenBao readiness blocks startup/readiness
N05  missing object-storage admission blocks the storage-dependent path
N06  missing generation readiness blocks required live planning
N07  unknown required domain activator is rejected
N08  restarted AE/WC/EOS workers do not settle work twice
N09  forbidden Golden Journey transition fixture is detected and fails audit
```

Missing, duplicate, unknown, tampered, wrong execution-class, private, or
partially passing evidence fails the aggregate.

## Worker Hardening

The S05 AE protected component now observes the deterministic runtime job while
it is still `QUEUED`, with attempt number zero and no persisted step result. It
then closes the first installed process, starts a replacement process to settle
the pending work, and starts one more process to prove replay does no work.

The S06 WC protected component now observes the handoff event as `ENQUEUED`
after signed-trust denial and confirms that AE has not resumed an execution.
The existing admitted restart then delivers exactly once. S07 already persisted
the denied EOS outbox as `PENDING`, recovered it after restart, and proved one
business mutation and one AE event.

## Dependency and Audit Boundaries

N04-N06 intentionally do not contact OpenBao, RustFS, or the generation
provider. Each scenario declares one required dependency and supplies no
admitted observation. The canonical readiness aggregate must return
`NOT_READY` with that exact dependency in `missing_required_dependency_ids`.
This is the fail-closed behavior under test, not a provider availability smoke.

N07 resolves an unregistered required capability and requires
`DOMAIN_INTENT_ACTIVATOR_REQUIRED`. N09 builds a temporary registered Golden
Journey fixture containing a forbidden `schedule_next()` call and requires the
repository audit to return `FORBIDDEN_TRANSITION_CALL`.

## Protected Evidence

The protected runner executed against the actual local test databases:

```text
nex_ae_test   / nex_ae_user
nex_wc_test   / nex_wc_user
nex_eos_test  / nex_eos_user
```

All three component migrations were current. N01-N09 passed, all protected
component reports declared actual PostgreSQL, and cleanup reported zero
remaining test-owned rows. Evidence contains no database URL, password, token,
private payload, or raw dependency value.

## Verification

```text
S19 focused regression                    = 28 passed / 1 protected skip
S19 protected PostgreSQL pytest            = 11 passed
N01-N09 protected runner                   = PASS (9/9, residue 0)
hidden-gap contract statement / branch     = 100% / 100%
S19 runner statement / branch              = 100% / 100%
ruff                                       = PASS
Platform Slice Gate                        = 420 passed / 8 skipped
Platform statement / branch                = 97.35% / 95.95%
contract validation                        = 227 / 291 / 245 / 10
Golden Journey transition audit            = PASS (9 registered, 1 enforced)
Demo-to-Product dependency audit            = PASS
```

The protected report is generated at
`reports/smoke/gb2-ca00-s19-fail-closed-restart.json` and remains ignored local
evidence.

## Exit

```text
missing installed link visible as failure  = YES
pending state durable across restart        = YES
duplicate settlement prevented              = YES
hidden smoke transition bypass accepted     = NO
test-owned PostgreSQL residue                = 0
next slice                                   = GB2-CA00-S20
```
