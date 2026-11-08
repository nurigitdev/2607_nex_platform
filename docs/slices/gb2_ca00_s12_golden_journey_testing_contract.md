# GB2-CA00-S12: Golden Journey Testing Contract and Enforcement Audit

## Scope

S12 freezes the distinction between component evidence and an installed
Platform Golden Journey. It adds no database migration, service API, business
behavior, or protected external dependency.

## Canonical Contract

The canonical contract is:

```text
docs/testing/Golden_Journey_Platform_Integration_Testing_Contract_v1.0.md
```

Before a request, a runner may prepare authoritative tenant, identity, Project,
business master, capability/Skill, and external dependency fixtures. After the
request enters through a public API or browser, only public interaction,
polling, read-only assertion, declared process restart, and cleanup are
permitted.

A `GOLDEN_JOURNEY` runner may not directly own:

```text
AgentExecution or RuntimeJob transition
WC WorkItem / Claim / Assignment / Approval / WorkResult transition
ResultDelivery acknowledgement
EOS BusinessOperation or outbox transition
WA evidence mutation
```

Component and protected-component tests may exercise their owning transition,
but cannot claim installed Platform continuity.

## Runner Registry and Audit

`scripts/quality/golden_journey_runners.v1.json` explicitly classifies the
seven current Journey-named Python runners. One current Chairman Journey is
classified as `GOLDEN_JOURNEY`; historical component, protected-component, and
evidence-aggregator runners remain available without being promoted.

`scripts/quality/run_golden_journey_transition_audit.py` fails closed on:

```text
unregistered or stale Journey runner
unsafe, duplicate, or non-canonical registry entry
forbidden transition-owning repository import
manual transition call such as schedule_next()
INSERT / UPDATE / MERGE against transition tables
missing, altered, or unexposed evidence metadata
unparseable enforced runner source
```

Read-only SQL and `DELETE` cleanup remain allowed. Business master insertion is
also allowed when it does not write a runtime-transition table.

## Evidence Metadata

The installed Chairman runner now projects:

```json
{
  "platform_integrated": true,
  "runtime_transition_fixture": false,
  "manual_domain_transition": false,
  "installed_process_continuity": true
}
```

These fields declare the runner contract; protected execution evidence remains
necessary before the run itself may claim PASS.

## Gate Integration

The audit is now mandatory in:

```text
Slice Gate
Checkpoint Gate
Full Gate
```

The independent Full Gate remains the fallback and does not depend on the
tiered runner.

## Verification

```text
focused audit/tiered tests             = 45 passed
Platform Slice Gate                    = 402 passed / 7 skipped
Slice statement / branch               = 97.35% / 95.95%
Checkpoint Gate                        = 17,763 passed / 131 skipped
Checkpoint statement / branch          = 98.22% / 96.67%
audit statement / branch               = 97.34% / 95.95%
contract validation                    = 226 / 290 / 244 / 10
registered / enforced Journey runners  = 7 / 1
Golden Journey transition audit        = PASS
ruff / diff check                      = PASS
database migration                     = NONE
protected PostgreSQL / provider smoke  = NOT REQUIRED
```

Protected tests skipped by the Checkpoint Gate retain their explicit
environment prerequisites; S12 changes no database or live-provider behavior.

## Exit

```text
Golden Journey contract                = CANONICAL
runner evidence classification         = EXPLICIT REGISTRY
manual transition mutation             = STATICALLY ENFORCED
canonical evidence metadata            = ENFORCED
Slice / Checkpoint / Full gate hook     = ACTIVE
CA00-TESTING-01                         = CLOSED
next slice                              = GB2-CA00-S13
```
