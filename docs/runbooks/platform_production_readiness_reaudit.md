# Platform Production Readiness Re-audit Runbook

## Purpose

This runbook reproduces the S141 repository audit and Full Gate. A passing
result means the platform boundary is ready for S142 packaging work. It does
not approve or execute a production deployment.

## Safety Boundary

- Do not export production credentials, endpoints, database URLs, provider
  keys, private payloads, signing keys, or storage references.
- The nine S141 runners inspect repository state and deterministic production
  profile admission only. They do not contact PostgreSQL, a browser, a model
  provider, an IdP, object storage, or an incident endpoint.
- Runtime evidence and coverage reports remain outside source control.
- Stop on any failed audit. Do not change counts or lower a gate to obtain a
  pass.

## Repository Audit

Run from the repository root:

```bash
./.venv/bin/python scripts/smoke/run_platform_production_readiness_boundary.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_deferral_inventory.py --summary
./.venv/bin/python scripts/smoke/run_platform_nonproduction_path_inventory.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_configuration_audit.py --summary
./.venv/bin/python scripts/smoke/run_platform_runtime_deployment_coupling_audit.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_responsibility_matrix.py --summary
./.venv/bin/python scripts/smoke/run_platform_operational_incompleteness_register.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_transition_dependency_plan.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_evidence_decision_contract.py --summary
./.venv/bin/python scripts/smoke/run_s141_platform_production_readiness_closure.py --summary
```

The closure summary must report `audits=9/9`, `deferrals=9`, `paths=9`,
`config_gaps=10`, `operations=12`, `requirements=9`, `fields=20`, and
`next=S142`.

## Full Gate

Run the unchanged repository gate without enabling protected production
profiles:

```bash
scripts/quality/run_quality_gate.sh
```

The gate must satisfy the repository statement and branch thresholds, validate
all JSON Schema/OpenAPI examples, and execute the S141 closure exactly once.
Opt-in protected smoke tests may remain policy skips; S141 does not use a skip
as evidence that any production gap is closed.

The accepted Slice 1411 run reported `12,052 passed`, `31 skipped`, statement
coverage `98.12%`, branch coverage `97.02%`, contract validation of `166`
schemas, `228` examples, `196` negative examples, and `7` OpenAPI documents.
The closure reported `audits=9/9` and `next=S142`.

## Failure Triage

1. A deferral, path, configuration, or responsibility mismatch is a canonical
   drift. Reconcile source evidence and `docs/48_platform_production_readiness_plan.md`.
2. A coupling change requires ownership review. Foreign domain imports,
   cross-service database reads, or non-MO provider calls are blockers.
3. An operational or dependency mismatch blocks S142 activation until the
   owner, target, and evidence mode are explicit.
4. An evidence/privacy failure blocks the program. Never persist a raw secret,
   token, URL, prompt, document, payload, private key, or physical path to make
   diagnosis easier.
5. A Full Gate failure leaves S141 unclosed. Fix the regression and rerun the
   complete gate.

## Rollback And Decision

- The accepted S140 release candidate remains the rollback baseline.
- All nine production deferrals and all twelve operational gaps remain open.
- The only S141 closure states are `READY_FOR_S142` and `BLOCKED`.
- `production_deployment_approved` and `production_resources_contacted` must
  both remain `false`.

## S142 Handoff

S142 owns immutable reproducible artifacts and explicit environment topology.
It must preserve service ownership and prove deterministic process lifecycle
without using production resources. External trust, data, model, monitoring,
and incident capabilities remain dependency-ordered work for S143-S150.
