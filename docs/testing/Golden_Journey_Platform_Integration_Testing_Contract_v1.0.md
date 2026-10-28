# Golden Journey Platform Integration Testing Contract v1.0

Status: Canonical

Owner: Platform Quality / Runtime

Effective from: GB2-CA00-S12

## 1. Purpose

A Golden Journey demonstrates installed Platform continuity. It is not a
component test with test-owned runtime transitions. This contract prevents a
runner from making its own success true by directly mutating the state that an
installed AE, WC, EOS, or WA process is expected to produce.

## 2. Evidence Classes

The repository recognizes these relevant classes:

| Class | Meaning | May claim Platform continuity |
| --- | --- | --- |
| `COMPONENT` | In-process contract or state behavior | No |
| `PROTECTED_COMPONENT` | Component behavior with protected dependency | No |
| `EVIDENCE_AGGREGATOR` | Collects already-produced evidence | No |
| `INSTALLED_PLATFORM` | Installed process or topology evidence | Only for its declared boundary |
| `GOLDEN_JOURNEY` | End-to-end installed business journey | Yes |

The file `scripts/quality/golden_journey_runners.v1.json` classifies every
Python runner whose filename contains `golden` or `chairman` and `journey`.
Adding such a runner without registering it is a quality-gate failure.

## 3. Request Boundary

Before the request enters the Platform, a runner may:

- seed tenant-scoped identity and business master data;
- seed Project, account, organization, or other authoritative fixture data;
- prepare external dependencies and temporary credentials;
- install versioned capability and Skill registration;
- clear residue owned by the same acceptance run.

After the request enters through the public API or browser, a runner may only:

- interact through public Platform API or browser surfaces;
- poll public/read-only projections;
- assert durable state without changing it;
- restart declared installed processes and verify recovery;
- delete acceptance-owned residue during final cleanup.

## 4. Forbidden Transition Ownership

A Golden Journey runner must not:

- call `MultiStepEngine.schedule_next()` or create a RuntimeJob directly;
- advance AgentExecution, executable step, wait, result, or delivery state;
- create WC WorkItem, Claim, Assignment, Approval, or WorkResult directly;
- acknowledge ResultDelivery directly;
- mutate EOS BusinessOperation or outbox state required by the journey;
- insert or update WA WorkEvidence or WorkAsset evidence;
- import transition-owning repositories to perform any of these operations.

SQL `SELECT` for assertion and `DELETE` for post-run cleanup are allowed. SQL
`INSERT`, `UPDATE`, or `MERGE` against the transition tables defined by the
audit is forbidden. Component tests may perform these operations while testing
the owning component, but their evidence class cannot be `GOLDEN_JOURNEY`.

## 5. Required Evidence Metadata

Every registered `GOLDEN_JOURNEY` report exposes exactly these semantic claims:

```json
{
  "platform_integrated": true,
  "runtime_transition_fixture": false,
  "manual_domain_transition": false,
  "installed_process_continuity": true
}
```

Source admission alone does not prove a live PASS. These fields state the
runner contract; protected evidence must still show that the declared services,
databases, providers, and browser execution actually ran.

## 6. Automated Enforcement

`scripts/quality/run_golden_journey_transition_audit.py` performs a fail-closed
repository audit:

1. discover Journey-named Python runners;
2. reconcile them with the canonical registry;
3. parse transition-enforced runners with Python AST;
4. reject forbidden repository imports and transition calls;
5. reject direct mutation SQL against runtime-transition tables;
6. require and verify the canonical evidence metadata projection.

The audit runs in Slice, Checkpoint, and Full Gates. Its report is written to
`reports/quality/golden-journey-transition-audit.json` and is not committed.

## 7. Review Rule

Static enforcement is deliberately conservative and complements code review.
Indirect mutation hidden behind a newly named helper is still a contract
violation even if it is not yet recognized by the scanner. Any new transition
API, repository, or table must update the audit vocabulary in the same Slice.
