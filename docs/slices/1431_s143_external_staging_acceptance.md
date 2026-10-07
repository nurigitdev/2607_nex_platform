# Slice 1431: S143 External Staging Acceptance

## Outcome

- Selected a single-host Docker Compose staging topology instead of requiring
  Kubernetes.
- Added digest-pinned OpenBao 2.7.1 and Traefik 3.7.14 services without a
  Docker socket, privileged containers, or host network mode.
- Added `staging_live` fail-closed admission for the same sixteen secret
  references, nine HTTPS endpoints, and six control values used by production.
- Added an HTTPS OpenBao AppRole/KV v2 resolver and per-owner process bootstrap.
  App containers receive only owner values; AE Web receives no secret-manager
  credential.
- Added integrated-Raft OpenBao configuration and OpenBao-PKI-issued Traefik
  certificates for six platform and three DGX provider routes.
- Added a network-disabled one-shot Raft volume ownership initializer using
  the pinned OpenBao image, fixed UID/GID, and only the `CHOWN` capability.
  Existing correct ownership makes repeated Compose evaluation a no-op.
- Kept service traffic on the internal control network while adding a
  dedicated admin bridge for Docker's loopback-only `8200` publish path.
- Included the value-free production configuration manifest in the five Python
  OCI contexts so packaged admission does not depend on repository mounts.
- Added a protected acceptance runner for actual five-test-database migration,
  six application images, three live DGX capabilities, owner-policy denial,
  secret v1/v2/v1 restart, TLS renew/rollback, and cleanup.

## Operational Decision

No additional host software is needed in the current environment. Docker
Engine, the Docker Compose plugin, and the repository Python environment are
already present. OpenBao and Traefik are pulled as digest-pinned OCI images;
the existing PostgreSQL test databases and DGX provider processes are reused.

This is external non-production staging evidence. It does not push images,
contact a production database, or approve production deployment. OpenBao
unseal/backup HA and production CA custody remain later production work.

## Verification

- Focused S143 contract and orchestration tests cover admission, owner-only
  materialization, OpenBao transport, bootstrap, PKI/runtime preparation,
  Compose validation, OCI context inclusion, and protected-runner sequencing.
- `docker compose config --quiet` accepts the complete topology with immutable
  application image references.
- Protected execution writes metadata-only evidence to
  `reports/deployment/s143-external-staging-acceptance.json`.
- Slice Gate remains required before the Slice commit. Slice 1432 owns the S143
  Full Gate and production-readiness handoff.
