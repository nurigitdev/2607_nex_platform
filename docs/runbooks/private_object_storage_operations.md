# Private Object Storage Operations Runbook

## Purpose

This runbook operates and reproduces the S146 private object-storage boundary
for the single-host Docker Compose topology. It covers RustFS bootstrap,
owner-scoped CX and AE access, migration, cutover, rollback, version restore,
restart recovery, credential rotation, protected acceptance, and closure.

A pass proves the accepted test-sized mechanics. It does not provide high
availability, automatic failover, multi-host durability, production-sized
capacity evidence, or production deployment approval. S149 owns integrated
staging load, failure injection, backup/restore, and recovery timing.

## Operating Boundary

- RustFS is the deployment runtime; CX and AE depend only on the
  S3-compatible application port.
- `nex-cx-private` and `nex-ae-private` are separate versioned buckets with
  separate IAM users and exact bucket policies.
- Traefik terminates managed TLS. RustFS publishes no host port in the
  source-controlled topology.
- OpenBao owns root, SSE-S3, CX, and AE credential values. Compose and Git hold
  references and file paths only.
- PostgreSQL stores ownership, hashes, sizes, versions, opaque storage
  references, lifecycle state, and vectors. Private payload bytes stay in
  RustFS.
- The named RustFS volume is a single-host failure domain. Versioning protects
  logical history, not host or volume loss.

Never put credentials, endpoints, object keys, source paths, filenames,
payloads, database URLs, or OpenBao tokens in source-controlled evidence,
shell history, command arguments, or tickets.

## Preflight

1. Confirm Docker Compose can render the S143, S144, and S146 layers.
2. Confirm the pinned RustFS image digest and non-root `10001:10001` identity.
3. Confirm the platform CA and managed certificate are current.
4. Confirm all 20 OpenBao references resolve without printing their values.
5. Confirm the five test database migrations are current before protected
   acceptance. Production database URLs are forbidden.
6. Confirm the RustFS data volume has sufficient capacity and is not mounted
   into any application container.
7. Confirm no stale acceptance containers, buckets, or named volumes exist.

Run the deterministic repository audits from the repository root:

```bash
./.venv/bin/python \
  scripts/smoke/run_s146_private_object_storage_boundary.py --summary
./.venv/bin/python \
  scripts/smoke/run_s146_object_storage_compose.py --summary
```

Both commands must report `pass`. The Compose audit must report two buckets,
two credentials, no host-published object port, and ten of ten checks.

## Bootstrap

1. Materialize the RustFS root access key, root secret key, and base64
   32-byte SSE-S3 master key into the private runtime directory.
2. Start Traefik and RustFS. Do not inject root credentials into CX or AE.
3. Wait for the RustFS health check and the Traefik TLS `/health` route.
4. Enable versioning and default `AES256` encryption on both buckets.
5. Apply the three lifecycle rules per bucket: incomplete multipart cleanup,
   tagged noncurrent-version retention, and expired delete-marker cleanup.
   The controlled entrypoint is
   `scripts/smoke/run_s146_object_storage_lifecycle.py` for each owner.
6. Provision one exact bucket policy and one service IAM user for CX and AE.
7. Test CX-to-AE and AE-to-CX access. Both attempts must be denied.
8. Start CX and AE only after their owner-scoped credentials and platform CA
   bundle are materialized.

Stop if root credentials reach an application container, a service can list
or address the other bucket, TLS verification is bypassed, versioning or
AES256 is absent, or the service silently falls back to local storage.

## Normal Operation

- Require immutable writes with SHA-256, size, content type, `AES256`, and an
  opaque reference before committing PostgreSQL metadata.
- Require owner authorization before resolving any object reference. Bucket
  policy remains defense in depth, not domain authorization.
- Monitor RustFS health, storage capacity, error rate, request latency,
  denied cross-bucket access, lifecycle errors, and credential age.
- Keep active payloads outside unconditional expiry. Only service-approved,
  unreferenced, hold-free versions receive the `nex-purge=eligible` tag.
- Treat a checksum, size, encryption, version, or ownership mismatch as an
  integrity incident. Do not retry it as ordinary transient availability.
- Keep evidence value-free. Record counts, reason codes, and aggregate digests
  only.

## Migration and Cutover

1. Build an owner-scoped migration manifest outside Git. Verify it contains
   only allowlisted relative paths and opaque target keys.
2. Run inventory-only mode first for each owner:

```bash
./.venv/bin/python scripts/smoke/run_s146_object_storage_migration.py \
  --owner nex-cx --manifest "$NEX_CX_MIGRATION_MANIFEST" --inventory-only
./.venv/bin/python scripts/smoke/run_s146_object_storage_migration.py \
  --owner nex-ae-api --manifest "$NEX_AE_MIGRATION_MANIFEST" --inventory-only
```

3. Copy each payload immutably, download it, and verify SHA-256, size, content
   type, and SSE-S3 metadata.
4. Set `OBJECT_FIRST` only after the object copy and transactional PostgreSQL
   reference update are verified. This is the dual-read observation phase.
5. Admit `OBJECT_ONLY` only after every inventory item is verified and the
   rollback window has elapsed.
6. Preserve filesystem sources. Source retirement requires a separate purge
   decision and is never performed automatically by the migration runner.

## Rollback

Rollback changes the read preference and matching metadata reference; it does
not delete either copy.

1. Stop owner writes if integrity is uncertain.
2. Set the affected owner to `FILESYSTEM_FIRST` with the explicit rollback
   admission flag.
3. Restore the matching PostgreSQL reference in the same controlled change.
4. Verify owner-scoped reads and hashes from the preserved filesystem source.
5. Keep new object versions and incident evidence. Do not purge while the
   incident is open.
6. Return to `OBJECT_FIRST`, then `OBJECT_ONLY`, only after a fresh verified
   copy and observation window.

## Version Restore

1. Authorize the tenant, subject, payload family, and exact opaque reference.
2. Select an exact historical version; never restore by an unbounded list.
3. Verify the historical payload's SHA-256, size, content type, and AES256
   metadata before publication.
4. Refuse restore over an active current version. Resolve the current logical
   state first.
5. Publish the historical bytes as a new immutable current version.
6. Download and verify the new current version, then update PostgreSQL state.
7. Record only hashed version references and metadata-only status.

## Credential Rotation

1. Provision a new owner-scoped IAM user and attach the existing exact bucket
   policy while the old identity remains valid.
2. Write the new pair as a new OpenBao version and materialize it into the
   owner-only runtime directory.
3. Restart only the affected service and verify readiness plus an owner-scoped
   write/read/delete-marker cycle.
4. Revoke the old IAM user after the observation window.
5. Test that the old identity is denied and the other owner remains healthy.
6. Rotate the RustFS root or SSE-S3 key only in a separately approved
   maintenance window. A root key change must not alter service IAM keys.

Never rotate by placing a new value in Compose, `.env`, logs, command-line
arguments, or a source-controlled report.

## Restart and Host Recovery

For a process restart, stop and start RustFS with the same named volume,
verify health through Traefik, and re-read known metadata-bound objects through
both application adapters. Do not recreate buckets or IAM users when durable
state is present.

For host or volume loss, stop the application write paths and escalate. S146
does not claim an independent RustFS backup or multi-host recovery path. Use
only an approved storage backup restored into an isolated volume, verify both
buckets, policies, versions, encryption, lifecycle rules, and sampled hashes,
then require an operator-controlled cutover. S149 must rehearse this path with
production-sized staging data.

## Protected Acceptance

Inject the five `NEX_*_TEST_DATABASE_URL` values without persisting them and
run:

```bash
NEX_S146_PROTECTED_ACCEPTANCE=1 \
./.venv/bin/python \
  scripts/smoke/run_s146_object_storage_acceptance.py \
  --execute --summary
```

A skipped run is not evidence. A pass must prove five current migrations, CX
and AE metadata-only PostgreSQL probes, two encrypted/versioned buckets,
separate IAM identities, cross-bucket denial, three adapter round trips, two
migrations with sources preserved, delete-marker restore, managed TLS,
non-root execution, named-volume restart recovery, and complete cleanup.

The ignored report must state that endpoints, object keys, payloads, and raw
values are absent. After execution, confirm no acceptance container or named
volume remains.

## Closure and Full Gate

```bash
./.venv/bin/python \
  scripts/smoke/run_s146_private_object_storage_closure.py \
  --summary
scripts/quality/run_quality_gate.sh
```

Closure must report all repository audits and checks passing, five databases,
two buckets, two owner migrations, zero residue, and `next=S147`. Full Gate
keeps protected acceptance opt-in disabled and validates the metadata-only
attestation instead of replaying a credentialed live run.

## Failure, Cleanup, and Escalation

Stop on owner-isolation failure, unencrypted write, disabled versioning,
checksum or size mismatch, missing historical version, silent filesystem
fallback, incomplete cleanup, raw value disclosure, or any production contact.

On an acceptance failure, preserve value-free diagnostics, remove every test
object version and delete marker, delete both ephemeral buckets, stop the
Compose project with volumes, remove the private runtime directory, and
confirm the five source test databases contain no persistent probe table.

Escalate integrity and ownership failures to CX, AE, and platform integration.
Escalate RustFS capacity, storage loss, backup/recovery, failure injection, and
production-sized lifecycle timing to S149. S148 consumes object-store health,
capacity, lifecycle, access-denial, migration, and restore telemetry.

## Handoff

S146 closes the single-host private object-storage migration and lifecycle
mechanics. S147 is next for production model-serving capacity and rollout
resilience. S148 may consume S146 telemetry; S149 must prove external backup,
host-loss recovery, production-sized capacity, and lifecycle timing before
S150 can consider a go-live decision.
