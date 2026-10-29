# P8 Chairman Demo Release Runbook

> Historical baseline: this runbook preserves the original Chairman Demo
> procedure. Current deployments must use
> `docs/runbooks/canonical_platform_deployment.md`. Former P8 deployment
> commands are compatibility wrappers and the old Compose/OCI path names are
> no longer active deployment sources.

## Release Boundary

This runbook operates the single-host P8 Chairman Demo release for tenant
`VO00`. It composes the existing OA, AG, AE, CX, MO, WC, EOS, AE Web, worker,
and daemon implementations. It does not authorize new business behavior,
registry push, production deployment, whole-database reset, or a mock fallback
for the protected journey.

The admitted durable targets are the seven owner-scoped `*_dev` PostgreSQL
databases. Runtime secrets come from OpenBao. RustFS stores private evidence.
The DGX generation provider is required for the protected Voucher journey.

## Prerequisites

Run commands from the repository root with:

```bash
git status --short
docker version
docker compose version
./.venv/bin/python --version
test -f .env.local
test -f reports/deployment/p8-nsl-v0.2.1-wheel/nex_skill_language-0.2.1-py3-none-any.whl
```

The tracked source used by the OCI build must be clean. The untracked local
`test/` directory is outside every image build context and must never be added
to release evidence. Load database URLs, provider credentials, and OpenBao
bootstrap values through the existing operator environment; never paste them
into a report or command transcript.

## Backup And Database Admission

Take a fresh seven-database backup before migrations or fixture changes:

```bash
./.venv/bin/python scripts/deployment/run_p8_demo_database_guardrails.py \
  --check \
  --backup \
  --backup-confirmation BACKUP_P8_DEMO_DEV_DATABASES \
  --backup-root /data/nex-platform/demo/postgres-backups \
  --summary
```

Use the generated backup manifest and its exact confirmation value with
`run_p8_demo_migrations.py`. Then rerun the guardrail check so the final report
records `7/7 CURRENT`. Seed and reset are limited to tenant `VO00` and require
the exact confirmation emitted by the fixture planner. Never use the test reset
helpers or a global truncate against the Demo databases.

## Build And Compose Admission

Build the complete non-root eight-image set from one clean revision:

```bash
NEX_P8_DEMO_OCI_IMAGE_BUILD=1 \
  ./.venv/bin/python scripts/deployment/build_p8_demo_images.py \
  --execute --summary
```

Build the admitted AE image with the NSL v0.2.1 wheel and Demo Skill bundle.
Use the `nex-ae-runtime` tag recorded by the image-set report as
`<BASE_IMAGE>`:

```bash
./.venv/bin/python scripts/deployment/build_p8_demo_ae_runtime_image.py \
  --base-image <BASE_IMAGE> \
  --output-image nex-platform-demo/nex-ae-runtime:p8-demo-release \
  --execute
```

Before rendering Compose, inject the admitted S11 semantic calibration policy.
The value is not a secret, but it is required explicitly so a missing or stale
INTENT/CONTEXT/PLAN policy fails closed:

```bash
export NEX_P8_DEMO_SEMANTIC_CALIBRATION_POLICIES_JSON='[{"adversarial_evidence_ref":"acceptance://p8-demo-s11/intent/adversarial","golden_evidence_ref":"acceptance://p8-demo-s11/intent/golden","minimum_confidence":0.5,"model_profile":"general-llm-default","model_ref":"Qwen3.5-4B","policy_ref":"semantic-admission://intent/p8-demo-s11/v1","policy_version":"p8-demo-s11-v1","semantic_stage":"INTENT"},{"adversarial_evidence_ref":"acceptance://p8-demo-s11/context/adversarial","golden_evidence_ref":"acceptance://p8-demo-s11/context/golden","minimum_confidence":0.5,"model_profile":"general-llm-default","model_ref":"Qwen3.5-4B","policy_ref":"semantic-admission://context/p8-demo-s11/v1","policy_version":"p8-demo-s11-v1","semantic_stage":"CONTEXT"},{"adversarial_evidence_ref":"acceptance://p8-demo-s11/plan/adversarial","golden_evidence_ref":"acceptance://p8-demo-s11/plan/golden","minimum_confidence":0.5,"model_profile":"general-llm-default","model_ref":"Qwen3.5-4B","policy_ref":"semantic-admission://plan/p8-demo-s11/v1","policy_version":"p8-demo-s11-v1","semantic_stage":"PLAN"}]'
```

Render and validate all Compose overlays against those exact image IDs:

```bash
NEX_P8_DEMO_COMPOSE_RENDER=1 \
  ./.venv/bin/python scripts/deployment/check_p8_demo_compose.py \
  --execute --summary
```

An incomplete image set, root runtime user, placeholder image, raw secret,
`*_test` database URL, or mismatched release-set digest is a stop condition.

## Trust And External Dependencies

Execute OpenBao owner isolation, AppRole rotation, signed-token audience/scope,
and TLS route admission:

```bash
NEX_P8_DEMO_TRUST_ADMISSION=1 \
  ./.venv/bin/python scripts/deployment/run_p8_demo_trust_admission.py \
  --execute --summary
```

Execute live provider and RustFS admission without mock fallback:

```bash
NEX_P8_DEMO_EXTERNAL_DEPENDENCIES=1 \
  ./.venv/bin/python scripts/deployment/run_p8_demo_external_dependencies.py \
  --execute --summary
```

Stop when generation readiness, all three provider identities, RustFS owner
isolation, restart recovery, managed TLS, or redaction checks fail.

## Installed Acceptance

The installed acceptance owns its temporary Compose project and cleanup:

```bash
NEX_P8_DEMO_S10_LIVE=1 \
  ./.venv/bin/python scripts/deployment/run_p8_demo_s10_installed_domain_acceptance.py \
  --execute --summary
```

It must report signed-only cross-service trust, current migrations, ready API
and background processes, renewed restart heartbeats, and zero post-restart
queues. Then execute the existing composition and result-closure gates:

```bash
NEX_P8_DEMO_S10B_LIVE=1 \
  ./.venv/bin/python scripts/smoke/run_p8_demo_s10b_installed_runtime.py \
  --execute --summary
NEX_P8_DEMO_S10C_LIVE=1 \
  ./.venv/bin/python scripts/smoke/run_p8_demo_s10c_installed_result_closure.py \
  --execute --summary
```

S10B and S10C must prove approval/WRITE execution plus final result
publication exactly once.

## Chairman Golden Journey

Run the protected browser journey only after image, database, trust, and
external dependency admission:

```bash
NEX_P8_DEMO_S11_LIVE=1 \
  ./.venv/bin/python scripts/deployment/run_p8_demo_s11_chairman_golden_journey.py \
  --execute --summary
```

The required path is login, immediate natural-language Voucher request,
planning, approval, controlled EOS commit, verification, result publication,
exact replay, restart, and authoritative browser recovery. Screenshots are
written under `reports/deployment/p8-demo-s11-screens/` for each visible state.

## Start And Readiness

For the supervised rehearsal, use only the image references emitted by the
admitted release report and the three Compose files in this order:

```text
deployment/compose/s143-staging.compose.yaml
deployment/compose/s146-object-storage.override.yaml
deployment/compose/p8-demo.override.yaml
```

Start infrastructure before APIs, APIs before background consumers, and the AE
Web ingress last. Admit the release only when all seven APIs, AE Web, AE Agent
Runtime dispatcher/worker, WC delivery, and EOS outbox ownership report ready.
Only Traefik exposes browser routes; PostgreSQL, RustFS, and OpenBao
administration remain private or loopback-bound.

## Stop And Restart

Stop intake first, allow bounded workers to finish or release leases, stop
background consumers, stop APIs, and stop infrastructure last. On restart,
reverse that order and verify:

```text
all required readiness checks pass
worker heartbeat is renewed
durable checkpoints resume
AE runtime job queue returns to zero
WC delivery queue returns to zero
EOS outbox queue returns to zero
Voucher and AgentResult counts remain exactly one
```

Do not reseed during recovery. A second business mutation, a changed result
hash, or a nonempty terminal queue blocks the release.

## Failure Triage

1. Preserve the failing redacted report and screenshots.
2. Stop the temporary Compose project without resetting databases.
3. Identify the first failed S12 check and its owner report.
4. For provider failure, confirm model alias/revision/dtype and rerun preflight.
5. For trust failure, rotate the affected owner credential and rerun admission.
6. For migration drift, restore or reconcile from the pre-migration backup.
7. For runtime failure, inspect heartbeat, lease, checkpoint, delivery, and
   outbox state before retrying.
8. Never replace a failed protected dependency with a mock to obtain PASS.

## Cleanup And Zero Residue

Acceptance runners remove temporary containers, Demo service principals,
credentials, signing keys, sessions, dynamic approval/runtime rows, and test
objects in `finally` boundaries. Verify no P8 Demo Compose containers remain
and no runtime queues or temporary OA trust rows remain. Preserve deterministic
tenant `VO00` fixture rows only when the operator explicitly chooses to keep
the Demo ready for presentation.

## Evidence And Release Closure

Run the Repository Full Gate after the final protected journey:

```bash
scripts/quality/run_quality_gate.sh
```

Then bind all evidence into one immutable Demo release candidate:

```bash
NEX_P8_DEMO_S12_RELEASE_CLOSURE=1 \
  ./.venv/bin/python scripts/deployment/run_p8_demo_s12_release_operations_closure.py \
  --execute --summary
```

The closure requires statement coverage at or above `96%`, branch coverage at
or above `94%`, a fresh JUnit result, 8/8 immutable images, 7/7 current Demo
databases, actual OpenBao/RustFS/PostgreSQL/generation/Playwright evidence, and
zero runtime residue. Its `p8-demo-rc:<digest>` identifier binds the source
revision, image set, AE NSL runtime image, Compose sources, NSL bundle, and
external dependency identity. Registry push and production deployment remain
separate, explicitly authorized operator actions.
