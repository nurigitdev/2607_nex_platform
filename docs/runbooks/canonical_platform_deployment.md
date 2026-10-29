# Canonical Platform Deployment

## Purpose

This runbook is the active deployment entrypoint for the current single-host
Platform. The historical P8-DEMO commands remain compatibility wrappers only.

## Installed Topology

The canonical release contains nine immutable images and twenty packaged
processes. Compose is layered in this order:

1. `deployment/compose/s143-staging.compose.yaml`
2. `deployment/compose/s146-object-storage.override.yaml`
3. `deployment/compose/canonical-platform.override.yaml`
4. `deployment/compose/p9-wa.override.yaml`

## Build And Admission

Build the complete release set without a registry push:

```bash
NEX_CANONICAL_PLATFORM_OCI_IMAGE_BUILD=1 \
./.venv/bin/python scripts/deployment/build_canonical_platform_images.py \
  --execute --summary
```

Render and admit the full Compose topology:

```bash
NEX_CANONICAL_PLATFORM_COMPOSE_RENDER=1 \
./.venv/bin/python scripts/deployment/check_canonical_platform_compose.py \
  --execute --summary
```

The image builder admits all nine image identities, non-root users, packaged
default commands, seven generic background lifecycle checks, and four direct
package checks for WA, AE runtime, WC delivery, and EOS publication processes.
The render-only admission injects an empty calibration list because it does
not start the runtime. Protected Golden Journey execution supplies the
admitted model-specific policies through
`NEX_CANONICAL_PLATFORM_SEMANTIC_CALIBRATION_POLICIES_JSON`.

## Protected Acceptance

Use the canonical trust, dependency, installed-platform, and golden-journey
commands for new evidence:

```text
run_canonical_platform_trust_admission.py
run_canonical_platform_external_dependencies.py
run_canonical_platform_installed_acceptance.py
run_canonical_platform_golden_journey.py
```

Each protected command remains double opt-in and writes redacted evidence
under `reports/deployment/`. Historical `run_p8_demo_*` command names delegate
to these modules and must not be used in new automation.

## Migration Boundary

`run_canonical_platform_migrations.py` promotes the existing guarded seven-core
database migration closure. NeX-WA retains its independently admitted P9
migration lifecycle; a future slice must unify backup admission before WA is
added to the guarded multi-database transaction boundary. The command does not
claim that one backup manifest currently covers WA.
