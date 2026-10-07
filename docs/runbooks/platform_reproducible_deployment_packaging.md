# Platform Reproducible Deployment Packaging Runbook

## Scope

This runbook reproduces the S142 repository audits and protected package-context
acceptance. It never authorizes production contact, image publication, registry
push, or deployment. Database credentials must come from the operator's local
secret injection mechanism and must not be written to reports or source files.

## Repository Audits

Run from the repository root:

```bash
./.venv/bin/python scripts/smoke/run_platform_deployment_packaging_boundary.py --summary
./.venv/bin/python scripts/smoke/run_platform_deployment_artifact_catalog.py --summary
./.venv/bin/python scripts/smoke/run_platform_deployment_build_inputs.py --summary
./.venv/bin/python scripts/smoke/run_platform_oci_build_definitions.py --summary
./.venv/bin/python scripts/smoke/run_platform_packaged_entrypoints.py --summary
./.venv/bin/python scripts/smoke/run_platform_environment_compositions.py --summary
./.venv/bin/python scripts/smoke/run_platform_packaged_lifecycle.py --summary
./.venv/bin/python scripts/smoke/run_platform_deployment_provenance.py --summary
```

All eight commands must report `pass`. The provenance command must report zero
built image digests unless an actual complete six-image set has been built and
recorded. Synthetic references prove only the complete-set algorithm.

## Protected Acceptance

Inject the five service-owned test database URLs into
`NEX_OA_TEST_DATABASE_URL`, `NEX_MO_TEST_DATABASE_URL`,
`NEX_CX_TEST_DATABASE_URL`, `NEX_AE_TEST_DATABASE_URL`, and
`NEX_AG_TEST_DATABASE_URL`. Then run:

```bash
NEX_PROFILE=test \
NEX_PLATFORM_PACKAGED_RUNTIME_ACCEPTANCE=1 \
./.venv/bin/python scripts/smoke/run_platform_packaged_runtime_acceptance.py --summary
```

Expected evidence is six materialized owner contexts, five migration/database
identities, seven background `--check` entrypoints, and two complete network
startup generations. The command must remain skipped when its opt-in is absent.
It must not contact model providers, a registry, staging, or production.

If the OCI daemon is inaccessible, the result records
`UNAVAILABLE_PERMISSION_OR_SOCKET` and does not claim an image build. Do not
change socket permissions or use privileged execution merely to turn this
metadata into a pass. Actual image execution belongs on an approved build host.

## Closure And Full Gate

```bash
./.venv/bin/python scripts/smoke/run_s142_platform_deployment_packaging_closure.py --summary
scripts/quality/run_quality_gate.sh
```

The closure must report eight of eight audits, six artifacts, thirteen process
bindings, five profiles, sixty-five packaged lifecycle process steps, zero
claimed final image digests, and `next=S143`.

## Failure And Recovery

1. A lock, context, Containerfile, binding, or composition mismatch blocks the
   artifact set. Regenerate nothing implicitly; reconcile the canonical source.
2. A migration identity or head mismatch blocks startup. Repair only the
   affected service-owned test database and rerun the protected acceptance.
3. A background check or readiness failure blocks restart evidence. Inspect the
   owner package context and service-local logs without exporting secrets.
4. A partial image set, mixed-version rollback, automatic database downgrade,
   or production contact fails closed.
5. Rollback selects the previous complete six-artifact identity and verifies
   compatibility with the already-migrated schema; it never downgrades the
   database automatically.
