# Platform Production Configuration, Secret, and TLS Lifecycle

Status: S143 complete through Slice 1432. Production deployment remains
unapproved.

## Required Outcome

S143 turns the S142 immutable release set and environment topology into a
fail-closed production configuration boundary. It must prove that configuration
is complete before startup, secret values are injected from external custody,
rotation is recoverable, provider API keys never enter artifacts or evidence,
and TLS certificate lifecycle is managed outside application containers.

The core requirement remains vendor-neutral. Its external staging realization
uses single-host Docker Compose, OpenBao, and Traefik; production may retain or
replace those adapters without changing the owner-scoped secret, HTTPS, or
metadata-only evidence contracts.

Actual external staging acceptance remains mandatory for every accepted S143
release set. Slice 1431 supplied its protected runner and a passing execution;
Slice 1432 binds that execution to a value-free attestation and Full Gate.

## Configuration Inventory

The existing production profile requires 25 values:

- 16 secret-bearing values: five database URLs, eight signed service-trust
  credentials, and three MO provider API keys;
- 9 public connection values: six platform service endpoints and three MO
  provider endpoints; and
- 9 network endpoints that must use HTTPS in production: the six service
  endpoints plus the three provider endpoints.

Runtime mode selectors, artifact digests, secret references, TLS references,
and rotation metadata are additional deployment inputs. They are not secret
values and must be validated independently.

## Trust Boundary

- Source, OCI images, deployment manifests, logs, exceptions, metrics, and
  exported evidence contain secret reference metadata only, never raw values.
- Secret references are opaque provider-neutral identifiers. Runtime values
  may be materialized only in the target process boundary and must not be
  echoed into child commands, reports, or health responses.
- Missing, empty, placeholder, stale, revoked, wrongly scoped, or partially
  rotated secrets block startup.
- Rotation uses prepare, activate, verify, retire, and rollback states. A new
  generation is not accepted until every required consumer is verified.
- Provider API keys remain MO-owned. Other services receive MO API contracts,
  never model-provider credentials.
- TLS terminates at a managed deployment boundary. Application artifacts do
  not embed private keys or certificate bundles.
- Certificate issuance, renewal, overlap, expiry alerting, revocation, and
  rollback must be observable through metadata-only evidence.
- Production admission requires immutable artifacts, exact configuration and
  secret generations, HTTPS endpoints, valid certificate references, and an
  explicit external protected acceptance result.

## Gap Register

| Gap ID | Owner | Target Slice | Required result |
| --- | --- | --- | --- |
| `typed_production_config_manifest` | Platform integration | `1424` | Typed manifest classifies every required value, reference, and owner. |
| `secret_classification_and_reference` | Platform integration and service owners | `1424` | Sixteen secret values map one-to-one to opaque external references. |
| `fail_closed_startup_admission` | Platform integration | `1425` | Startup rejects incomplete, placeholder, insecure, or mixed-generation configuration. |
| `external_secret_injection` | Platform integration and service owners | `1426` | Provider-neutral resolver materializes only owner-scoped process inputs. |
| `secret_rotation_reload_rollback` | Platform integration and service owners | `1427` | Rotation, reload/restart, verification, retirement, and rollback are deterministic. |
| `api_key_custody_redaction` | MO and Platform integration | `1428` | Provider keys stay MO-only and all evidence remains value-free. |
| `managed_tls_termination` | Platform integration | `1429` | HTTPS and managed termination references are required for production. |
| `certificate_renewal_expiry_rollback` | Platform integration | `1429` | Renewal overlap, expiry alert, revocation, and rollback lifecycle is explicit. |
| `protected_staging_acceptance` | Platform integration | `1430`, `1431` | Local rehearsal and actual external staging evidence both pass without secret disclosure. |

All gaps began `OPEN`. Repository implementation or local loopback evidence
alone cannot mark `protected_staging_acceptance` complete. Slice 1432 closes
the nine S143 gaps for the accepted non-production staging release set; a new
release set must produce fresh protected evidence.

Slice 1424 implements the typed manifest and one-to-one secret-reference
classification. Runtime materialization and startup admission remain open.

Slice 1425 implements metadata-only pre-start admission. Slice 1426 implements
provider-neutral resolution and exact owner-scoped process environments without
publishing raw values or opaque references. External-provider acceptance,
and post-materialization runtime validation remain open. Slice 1427 freezes
owner-ordered rolling restart, all-owner verification before retirement, and
reverse-order rollback for rotation failures.

Slice 1428 enforces MO-only custody for all three provider API keys and adds a
value-aware recursive redaction boundary. Raw values and their hashes remain
forbidden in evidence.

Slice 1429 fixes managed TLS termination, end-to-end HTTPS, certificate
overlap verification, expiry alerting, revocation blocking, and rollback. No
application image or process may receive TLS private-key material.

Slice 1430 performs actual local owner-process injection, generation rollback,
loopback HTTPS certificate replacement/rollback, and zero-residue cleanup.
The protected rehearsal passed with five candidate owner processes, five
rollback owner processes, three HTTPS probes, zero residue, and direct
private-value/evidence comparison. This evidence remains explicitly
non-production and non-external.

Slice 1431 selects the deliberately small staging topology: Docker Compose
orchestrates six application images, OpenBao integrated Raft owns KV v2,
owner-specific AppRole, and staging PKI, and Traefik owns HTTPS ingress for six
platform routes and three DGX routes. The existing five PostgreSQL test
databases are reached through `host.docker.internal`; the existing DGX
providers remain external upstreams. Neither OpenBao nor Traefik requires a
host package installation.

OpenBao remains a non-root runtime. A network-disabled one-shot initializer,
using the same digest-pinned image, grants the named Raft volume to UID 100 and
GID 1000 with only the `CHOWN` capability before startup. It checks the current
owner first, so later Compose evaluation is an idempotent no-op. The runtime
joins the internal `control` network and a separate `admin` bridge; only the
latter is used to publish the TLS administration endpoint on
`127.0.0.1:8200`.

The protected acceptance must prove v1 startup, owner-policy denial, v2 rolling
restart, certificate renewal, v1 and prior-certificate rollback, real
PostgreSQL readiness, live provider route health, immutable image use, and
cleanup. Reports contain metadata only. Production deployment remains blocked
until Slice 1432 closure and the later S144-S150 controls.

Slice 1431 passed that protected acceptance against five actual test databases,
six immutable application images, and all three live provider capabilities.
OpenBao owner isolation, generation `1,2,1`, nine Traefik routes, certificate
renewal and rollback, six-service readiness for all three generations, and zero
Compose residue passed. The ignored detailed report is bound by digest into
the source-controlled, value-free Slice 1432 attestation.

## Slice Sequence

| Slice | Scope |
| --- | --- |
| `1423` | Current-state boundary audit, inventory, ownership, and non-drift rules. |
| `1424` | Typed production configuration and secret-reference manifest. |
| `1425` | Fail-closed startup admission and safe diagnostics. |
| `1426` | External secret resolver and owner-scoped injection contract. |
| `1427` | Secret rotation, reload/restart, rollback, and fifth-Slice Checkpoint Gate. |
| `1428` | Provider API-key custody, least privilege, and redaction hardening. |
| `1429` | Managed TLS termination and certificate lifecycle contract. |
| `1430` | Protected local secret-rotation and TLS lifecycle rehearsal. |
| `1431` | Protected external staging secret-manager and managed-TLS acceptance. |
| `1432` | S143 closure, runbook, Full Gate, and S144-S147 handoff. |

## Non-Drift Rules

- OA, AE, CX, MO, and AG retain service-local ownership; platform integration
  coordinates injection and TLS without reading service domain data.
- Only MO may receive embedding, reranking, or generation provider API keys.
- OA external signing-key custody remains S144 and is not collapsed into S143.
- Database HA/backup, object storage, GPU scheduling, and monitoring remain
  S145-S148 responsibilities.
- Local environment values and loopback TLS are deterministic test adapters,
  never production evidence.
- No Slice performs registry push or production deployment.
- Slice Gate runs for every Slice, Checkpoint Gate at Slice 1427, and Full Gate
  at Slice 1432.

## Staging Prerequisites

- Docker Engine and the Docker Compose plugin on the single staging host;
- six current immutable local OCI image references from the S142 build;
- five existing localhost PostgreSQL test database URLs;
- reachable DGX provider endpoints at ports 9111, 9112, and 9113 plus their
  protected API-key inputs; and
- an operator-controlled runtime directory, created temporarily by the
  protected runner or persistently under `/data/nex-platform/staging`.

OpenBao and Traefik are OCI image dependencies, not host-installed software.
Kubernetes, Helm, a service mesh, and external notification endpoints are not
S143 prerequisites.

## Closure Decision

S143 is complete for the accepted non-production staging release set. Seven
deterministic audits, the single-host Compose contract, protected PostgreSQL
and live-provider execution, owner-scoped secret rotation, managed TLS renewal
and rollback, privacy checks, and zero residue are bound by the closure runner.
No image was pushed, no production resource was contacted, and production
deployment remains unapproved.

The host software boundary is frozen: the existing Docker Engine, Docker
Compose plugin, Git, and repository Python environment are sufficient.
OpenBao and Traefik remain digest-pinned container dependencies, not host
packages. The repeatable procedure is recorded in
`docs/runbooks/platform_production_configuration_secret_tls.md`.

Completion signal: Met.

## S144-S147 Handoff

The dependency gate now permits S144 through S147 to proceed independently:

- S144: OA external signing-key custody, rotation, and enterprise federation;
- S145: five-database backup, restore, failover, RPO, and RTO;
- S146: CX/AE private object-storage migration and lifecycle; and
- S147: model-serving capacity, canary, calibration, failover, and rollback.

S148 cannot close until all four handoffs emit their protected evidence. S149
and S150 remain blocked by the canonical dependency plan.
