# Platform Production Configuration, Secret, and TLS Runbook

## Purpose

This runbook reproduces S143 repository audits, local rehearsal, protected
single-host staging acceptance, closure, and Full Gate. A pass proves the
production-shaped configuration, external secret, and managed TLS boundary in
non-production staging. It does not approve a registry push or production
deployment.

## Software Boundary

No host installation of OpenBao or Traefik is required. The staging host needs
only the already-installed Docker Engine, Docker Compose plugin, Git, and the
repository Python environment. OpenBao and Traefik run from digest-pinned OCI
images. Kubernetes, Helm, a service mesh, a host OpenBao binary, a host Traefik
package, Vault, Certbot, Nginx, and an external container registry are not S143
prerequisites.

The external dependencies are the five existing PostgreSQL test databases and
the three reachable DGX provider capabilities. Credentials and endpoints must
come from the operator's protected environment and must never be written into
source files, shell history, or exported evidence.

## Repository Audits

Run from the repository root:

```bash
./.venv/bin/python scripts/smoke/run_platform_production_security_boundary.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_configuration_manifest.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_startup_admission.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_secret_materialization.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_secret_rotation.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_api_key_custody.py --summary
./.venv/bin/python scripts/smoke/run_platform_production_tls_lifecycle.py --summary
```

All seven commands must report `pass`. The inventory must remain 25 required
values, 16 external references, 9 public HTTPS connections, 5 secret-consuming
owners, and 3 MO-owned provider credentials.

## Protected Local Rehearsal

The local rehearsal uses temporary owner processes and loopback TLS. It is a
preflight, not a substitute for external staging:

```bash
NEX_PROFILE=test \
NEX_S143_LOCAL_SECURITY_REHEARSAL=1 \
./.venv/bin/python \
  scripts/smoke/run_platform_production_security_local_rehearsal.py \
  --execute --summary
```

Expect five candidate processes, five rollback processes, three HTTPS probes,
and zero residue.

## OCI Release Set

The protected staging runner consumes the ignored S142 six-image build report.
On a clean committed tree, rebuild it when runtime, dependency, Containerfile,
or included deployment input changes:

```bash
NEX_PLATFORM_OCI_IMAGE_BUILD=1 \
./.venv/bin/python scripts/deployment/build_platform_images.py \
  --execute \
  --report reports/deployment/s142-oci-image-build.json \
  --summary
```

The command must report six images, six manifests, six non-root users, seven
background checks, a complete release set, no push, and no production contact.

## Protected External Staging Acceptance

Inject the five `NEX_*_TEST_DATABASE_URL` values and the three MO provider
credential values through the approved local mechanism. Do not place them in a
Compose `.env` file. The database URLs must identify the localhost PostgreSQL
test databases; the runner translates their container host boundary. Then run:

```bash
NEX_PROFILE=test \
NEX_S143_EXTERNAL_STAGING_ACCEPTANCE=1 \
./.venv/bin/python scripts/smoke/run_s143_external_staging_acceptance.py \
  --execute \
  --report reports/deployment/s143-external-staging-acceptance.json \
  --summary
```

Expected evidence is five migrated databases, six ready application services
before and after rotation and rollback, three live provider capabilities,
cross-owner denial, secret generations `1,2,1`, nine managed TLS routes,
certificate renewal and rollback, and zero Compose residue. The report is
metadata only and ignored by Git.

The source-controlled attestation records only the accepted source, artifact,
configuration, and report digests plus counts and booleans. It does not replace
the protected report for incident diagnosis and cannot be edited to manufacture
a pass. A new release set or configuration requires a new protected run and a
new attestation.

## Closure And Full Gate

```bash
./.venv/bin/python \
  scripts/smoke/run_s143_production_configuration_secret_tls_closure.py \
  --summary
scripts/quality/run_quality_gate.sh
```

Closure must report seven of seven audits, 16 external references, 9 Compose
services, 5 actual test databases, 3 live provider capabilities, 9 TLS routes,
and `next=S144`. Full Gate runs protected runners without their opt-in flags;
those commands remain explicit policy skips while the closure validates the
already accepted value-free attestation.

## Failure And Recovery

1. A manifest, owner, generation, or HTTPS mismatch blocks startup. Reconcile
   the canonical configuration rather than weakening admission.
2. A database migration or identity failure blocks all application startup.
   Repair only the affected service-owned test database and rerun migration.
3. An OpenBao policy failure blocks rotation. Preserve the prior generation,
   restore owner credentials, and recreate application services in reverse
   owner order.
4. A provider route failure blocks acceptance but never transfers provider
   credentials out of MO custody.
5. A certificate probe failure restores the prior certificate and restarts
   Traefik before any candidate generation can be accepted.
6. Always run `docker compose down --volumes --remove-orphans` with the same
   protected runtime environment after manual interruption. Containers,
   networks, volumes, temporary credentials, and certificate files must leave
   zero residue.

## Handoff

S143 closes only the external configuration, secret, and TLS boundary. S144
owns OA signing-key custody and federation, S145 owns PostgreSQL resilience,
S146 owns private object storage, and S147 owns model-serving capacity and
rollout resilience. These requirements may proceed independently after S143.
Production deployment remains unapproved.
