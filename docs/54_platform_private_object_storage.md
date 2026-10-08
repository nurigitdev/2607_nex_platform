# Private Object Storage Migration and Lifecycle

Status: CX and AE adapters, migration/rollback, lifecycle/restore controls,
and the single-host RustFS Compose topology are complete at Slice 1460.
Protected acceptance remains open; production deployment remains unapproved.

## Required Outcome

S146 moves private CX and AE payload bytes out of process-local filesystem
roots and behind explicit object-storage ports. PostgreSQL continues to own
queryable metadata, hashes, sizes, opaque storage references, ownership, and
pgvector values. RustFS is the accepted single-host object-storage runtime,
while application code depends only on the S3-compatible API boundary.

## Technology and Topology Decision

- RustFS runs as a non-root service in the existing single-host Docker Compose
  topology and is reachable only on the internal service network.
- The pinned RustFS image is admitted by digest. Registry push and Kubernetes
  are outside S146.
- `nex-cx-private` and `nex-ae-private` are separate versioned buckets with
  separate service credentials. Root/bootstrap credentials are never supplied
  to application containers.
- Traefik terminates the managed S143 TLS connection. Plain HTTP is confined
  to the private Compose service network between Traefik and RustFS.
- OpenBao provides RustFS bootstrap and service credential references. Raw
  keys never enter Compose files, source-controlled evidence, logs, or CLI
  arguments.
- Every write requests server-side encryption with `AES256` (SSE-S3), records
  a SHA-256 and size, and returns an opaque `s3://bucket/key` reference.
- Local filesystem adapters remain available for development, test, and
  explicitly rehearsed rollback. Staging and production fail closed instead
  of silently selecting local storage.

## Payload Inventory

| Owner | Payload family | Current durable bytes | S146 target |
| --- | --- | --- | --- |
| CX | uploaded source documents | `/data/nex-platform/cx/source-files` | `nex-cx-private/source/` |
| CX | extracted Markdown | `/data/nex-platform/cx/extracted-markdown` | `nex-cx-private/extracted/` |
| CX | private chunk and summary text | `/data/nex-platform/cx/private-text` | `nex-cx-private/text/` |
| CX | generation request payloads | `/data/nex-platform/cx/generation-requests` | `nex-cx-private/generation-request/` |
| CX | generated output and structured draft | `/data/nex-platform/cx/generated-outputs` | `nex-cx-private/generation-output/` |
| AE | generated chat response content | configured response root or memory | `nex-ae-private/chat-response/` |
| AE | rendered artifact bytes | configured artifact root or memory | `nex-ae-private/artifact/` |

Vectors remain in CX PostgreSQL/pgvector. PostgreSQL backups, MO model files,
OpenBao data, logs, reports, and temporary extraction work files are outside
the S146 object-storage migration.

## Ownership and Object-Key Contract

Object keys are deterministic, versioned, and contain no raw tenant ID,
subject ID, source filename, prompt, document text, or chat content. Owner
scope and content identity are one-way SHA-256 digests. The canonical form is:

`v1/<payload-family>/<owner-prefix>/<owner-digest>/<content-digest>.<suffix>`

Uploaded CX source bytes are the deliberate exception to the owner digest
layout. They use `v1/source/<sha-prefix>/<sha256>.<suffix>` so the existing
global physical deduplication by source hash remains effective. These objects
are CX-internal and cannot be addressed through an end-user API. Authorization
is enforced through owner-scoped `content_object` references, and a source
object cannot be retired until its durable reference count reaches zero.
Extracted Markdown and every other private payload remain owner scoped.

CX and AE enforce owner authorization before resolving any object reference.
Bucket policy is a second boundary, not a replacement for service-domain
authorization. Listing is never part of an end-user API. Metadata records keep
only opaque references, hashes, sizes, content types, version identifiers when
required for restore, and service-owned lifecycle state.

## Migration and Rollback Contract

Migration uses inventory, copy, integrity verification, dual-read, cutover,
and source retirement phases. A target object is admitted only when its
downloaded SHA-256 and size match the source. During dual-read, new writes go
to RustFS and reads try RustFS before the legacy filesystem. Rollback changes
the read preference only; it never silently rewrites or deletes either copy.

Filesystem source retirement starts only after a complete owner-scoped
inventory is verified, the rollback window has elapsed, and a separate purge
decision is recorded. Migration state and evidence contain counts and digests,
not physical paths or payload bytes.

## Versioning, Retention, and Restore

- Both buckets have versioning enabled before application writes are admitted.
- Current application deletes create recoverable delete markers during the
  rollback window; destructive version purge is a separate lifecycle action.
- Noncurrent versions and delete markers are retained for 30 days by default.
- Incomplete multipart uploads expire after 7 days.
- Active private payloads have no unconditional expiry. Service-owned logical
  retention and legal-hold decisions remain authoritative.
- Restore verifies bucket, key, version, SHA-256, size, owner scope, and
  content type before a restored version becomes readable.

S149 must revalidate lifecycle timing with production-sized staging data.

## Gap Register and Slice Sequence

| Slice | Gap | Required result |
| --- | --- | --- |
| `1453` | `object_storage_boundary` | Freeze RustFS/S3 topology, payload inventory, ownership, migration, rollback, and exclusions. |
| `1454` | `s3_client_foundation` | Implement fail-closed S3 configuration, client port, immutable put/get/head/delete, and health checks. |
| `1455` | `cx_private_text_adapter` | Move CX private text families behind the object-storage adapter. |
| `1456` | `cx_document_blob_adapter` | Move CX source and extracted Markdown bytes behind object storage and hydration ports. |
| `1457` | `ae_private_payload_adapter` | Move AE generated responses and artifacts behind object storage. |
| `1458` | `migration_and_rollback` | Inventory, copy, verify, dual-read, cutover, rollback, and zero-data-loss guards. |
| `1459` | `lifecycle_and_restore` | Bootstrap buckets, encryption, versioning, retention, delete markers, and restore verification. |
| `1460` | `single_host_compose` | Integrate pinned RustFS, OpenBao references, TLS route, health, and non-root persistence. |
| `1461` | `protected_acceptance` | Exercise real RustFS with CX/AE adapters, migration, lifecycle, restore, restart, and cleanup. |
| `1462` | `closure` | Bind metadata-only evidence, publish runbook, pass Full Gate, and activate S147. |

Checkpoint Gate runs at Slice 1457 and Full Gate at Slice 1462.

## Implemented CX Document Boundary

- `NEX_CX_PRIVATE_STORAGE_MODE=FILESYSTEM` preserves the local compatibility
  adapter; `S3` selects the RustFS-compatible object port and fails closed when
  configuration is incomplete.
- Source bytes are published immutably under a content-addressed key, verified
  before `checksum_verified_at` is recorded, and can be re-read after process
  memory is cleared.
- Extracted Markdown is published under an opaque owner-scoped key. PostgreSQL
  keeps only its URI, SHA-256, character count, extractor lineage, and status.
- Restart hydration downloads and verifies Markdown into
  `extraction_temp_root/hydrated`; downstream chunking and summary code sees a
  verified temporary file, not a durable filesystem payload.
- The filesystem paths remain compatible for local development and explicit
  rollback, while S3 registrations do not persist a physical source path.

## Implemented AE Private Payload Boundary

- `NEX_AE_PRIVATE_STORAGE_MODE=S3` selects the RustFS-compatible adapter for
  generated chat responses and rendered artifact files. Explicit filesystem
  mode requires the corresponding local root; missing or invalid protected
  configuration fails closed.
- Generated response object keys are derived from the persisted chat record's
  tenant and owner subject. The existing logical response reference and
  lineage schema remain unchanged, so object keys and owner identifiers do not
  enter chat responses or operations evidence.
- Artifact display names remain PostgreSQL metadata for browser downloads,
  while new `ae://artifacts/v1/...` references contain only owner and content
  digests plus the format extension.
- S3 reads verify expected SHA-256 and size, writes are immutable SSE-S3
  publications, and retention deletes create the object-store delete boundary
  before graph rows are removed.
- Existing memory and filesystem adapters remain available for tests, local
  development, and explicit rollback; they are not silently selected when an
  S3 profile is requested.

## Implemented Migration And Rollback Control Plane

- `object_storage_migration_manifest.v1` is a runtime-only manifest of opaque
  item IDs, relative source paths, target keys, expected hashes, sizes, and
  content types. Manifests contain operational paths and keys and must not be
  committed or copied into evidence.
- Inventory rejects unsafe roots, symlinks, traversal, duplicate source or
  target entries, invalid metadata, and source hash/size drift. Copy re-reads
  every source, publishes immutably with SSE-S3, downloads the target, and
  verifies its bytes and metadata before recording completion.
- Evidence includes only counts, total bytes, aggregate digests, phase, and
  reason codes. It never includes payloads, physical paths, or object keys.
- `OBJECT_FIRST` is the migration dual-read mode. `FILESYSTEM_FIRST` is the
  rollback preference. Both require an explicit owner-scoped admission flag;
  fallback occurs only when the preferred copy is missing, never after an
  integrity or availability error.
- New CX private text and AE generated-response writes always go to object
  storage while either dual-read mode is active. Deletes affect only the
  object copy; the migration layer has no filesystem delete operation.
- `OBJECT_ONLY` requires a complete verified copy and an elapsed rollback
  window. Source retirement additionally requires a separately recorded purge
  decision, and the migration runner still does not perform that purge.
- CX source/extracted records and AE artifact records carry backend or storage
  references in PostgreSQL. Their object copy does not authorize cutover until
  a protected, transactional metadata-reference update is verified. Rollback
  must restore read preference and the matching metadata reference together.

The executable operator boundary is
`scripts/smoke/run_s146_object_storage_migration.py`. Source roots are supplied
through `NEX_CX_OBJECT_STORAGE_MIGRATION_ROOT` or
`NEX_AE_OBJECT_STORAGE_MIGRATION_ROOT`; they are never CLI output. Runtime read
preferences use `NEX_CX_OBJECT_STORAGE_READ_MODE` and
`NEX_AE_OBJECT_STORAGE_READ_MODE`. `OBJECT_FIRST` requires the corresponding
`*_OBJECT_STORAGE_MIGRATION_ADMITTED=true`, and `FILESYSTEM_FIRST` requires
`*_OBJECT_STORAGE_ROLLBACK_ADMITTED=true`.

## Implemented Lifecycle And Restore Controls

- The bucket bootstrap applies and reads back versioning `Enabled`, default
  `AES256` encryption, a 7-day incomplete multipart abort rule, a tagged
  noncurrent-version retention rule, and expired delete-marker cleanup.
- Noncurrent versions are not unconditionally expired. The 30-day rule applies
  only to versions tagged `nex-purge=eligible` after the service proves zero
  active references, no legal hold, a recorded purge decision, and an elapsed
  rollback window. Existing classification tags are preserved.
- Delete-marker cleanup applies only after no retained object version remains.
  A held or unapproved version remains untagged and therefore prevents an
  expired delete marker from becoming eligible.
- Restore requires the authorized object-key prefix, exact source version ID,
  expected SHA-256, size, content type, and SSE-S3 metadata. It downloads and
  verifies the historical version before publishing it as a new immutable
  current version, then downloads the new current version again.
- Restore refuses to overwrite an active current version. Operational evidence
  hashes bucket and version identifiers and does not disclose keys, payloads,
  endpoints, or credentials.
- `scripts/smoke/run_s146_object_storage_lifecycle.py` uses dedicated bootstrap
  credentials from `NEX_OBJECT_STORAGE_BOOTSTRAP_*`; CX and AE application
  credentials are not reused for bucket administration.

## Implemented Single-Host Compose Topology

- `deployment/compose/s146-object-storage.override.yaml` layers on the
  unchanged S143 and S144 files. It pins RustFS 1.0.1 to an immutable
  multi-architecture manifest digest and introduces no Docker socket,
  privileged mode, host networking, Kubernetes, or registry push.
- RustFS uses the official non-root `10001:10001` identity, a read-only root
  filesystem, dropped capabilities, a named `/data` volume, internal-only
  object-storage network, disabled console, and `/health` readiness probe. It
  publishes no host port.
- Traefik terminates managed TLS for `object.nex-staging.test` and is the only
  process that can reach the internal RustFS HTTP listener. The S143 platform
  certificate and CA remain the application trust anchor.
- Root access and secret keys enter RustFS through Docker secret files. The
  files are runtime outputs of OpenBao materialization and are not values in
  Compose, environment, source, reports, or command arguments.
- The SSE-S3 local master key is a separate OpenBao value materialized as a
  Docker secret. A minimal wrapper entrypoint exports the base64-encoded
  32-byte value only to the RustFS process because RustFS 1.0.1 does not expose
  a corresponding `_FILE` setting. CX and AE never receive this key.
- The current production manifest contains 20 secret references and 11 HTTPS
  connection bindings. CX and AE each own their own access/secret pair; other
  owners carry only the references needed for complete pre-start admission.
  Owner-scoped materialization prevents those services from receiving CX or
  AE values.
- CX and AE select `S3`, separate buckets, platform CA verification, and
  fail-closed `OBJECT_ONLY` by default. Migration and rollback modes remain
  explicit operator-gated overrides.

`scripts/smoke/run_s146_object_storage_compose.py` validates this topology.
The rendered three-layer Compose configuration also passed the host Docker
Compose parser.

## Protected Acceptance Evidence

- `scripts/smoke/run_s146_object_storage_acceptance.py` is opt-in through
  `NEX_S146_PROTECTED_ACCEPTANCE=1` and `--execute`. It uses all five real test
  PostgreSQL databases and an ephemeral single-host OpenBao, Traefik, and
  RustFS Compose deployment.
- OpenBao materializes RustFS root and SSE-S3 bootstrap secrets before the
  container starts. Root credentials perform only bucket and IAM bootstrap;
  separate bucket-scoped CX and AE users perform application operations.
- Both buckets proved versioning, default AES256 encryption, three lifecycle
  rules, CX/AE cross-bucket denial, managed-TLS routing, non-root execution,
  named-volume persistence, restart recovery, and delete-marker restore.
- The real CX source/Markdown adapters and AE generated-response adapter
  completed encrypted write/read verification. RustFS returns user metadata
  keys with preserved capitalization, so the product-neutral S3 port now
  treats metadata names case-insensitively as required by S3 semantics.
- CX and AE migration copied and verified one private payload each, admitted
  `OBJECT_ONLY`, and preserved both legacy sources. PostgreSQL probes persisted
  only hash, size, and opaque reference fields in temporary metadata tables;
  no payload column or payload byte was introduced.
- Cleanup removed every object version and delete marker, both buckets, all
  containers, and the named volumes. The report contains counts and aggregate
  digests only and keeps credentials, endpoints, object keys, filesystem
  paths, and payloads absent.

## Non-Drift Rules

- RustFS is the deployment product; S3 compatibility is the application port.
- No RustFS-specific SDK or admin API may enter CX or AE domain code.
- Raw private payloads remain outside PostgreSQL except existing queryable
  pgvector and metadata values.
- No cross-service bucket or direct cross-service object access is allowed.
- No raw credentials, endpoints, private payloads, physical paths, or object
  keys enter source-controlled evidence.
- Local filesystem and in-memory payload stores are forbidden in protected
  production-shaped profiles unless rollback mode is explicitly admitted.
- Migration never deletes the source automatically, and lifecycle never
  overrides a service-owned hold or active record.
- Object storage does not replace PostgreSQL backup, database ownership, TLS,
  or service authorization controls.
- Production contact and production deployment approval remain outside S146.

## Stop Conditions

Stop before protected acceptance if RustFS cannot prove S3-compatible
versioning, SSE-S3, delete-marker restore, non-root persistence, TLS-routed
access, restart recovery, or separate CX/AE credentials. Also stop if payload
integrity cannot be checked end to end, an owner can address another owner's
object, a local fallback is silent in staging/production, migration can delete
a source before verification, or evidence would disclose a credential,
endpoint, object key, physical path, or payload.
