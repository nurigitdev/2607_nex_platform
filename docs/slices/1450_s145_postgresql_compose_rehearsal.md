# Slice 1450: S145 PostgreSQL Compose Rehearsal

## Outcome

- Added a `postgres-operations` Docker Compose profile that is absent from
  normal application startup.
- Added a non-root recovery-tool image based on digest-pinned PostgreSQL 16.9
  and an externally supplied NeX Python runtime image.
- Kept the six application artifacts unchanged; the operator is a separately
  versioned operations artifact.
- Bound backup and worker-state storage through distinct host mounts and
  mounted the libpq service/pass files as external secrets.
- Rehearsed five logical backup plans, one durable worker run, five atomic
  archives, and five clean catalogs without database contact.

## Container Evidence

The local operator image built successfully. The actual Compose profile then
ran `--check` as UID/GID 65532 and reported PostgreSQL major 16, three required
tools, and two credential sources. The temporary container, network, bind
mounts, and synthetic credentials were removed after the check.

The locally inspected Python runtime tag was used only because S142 did not
push images. Production requires a registry-resolvable immutable Python
runtime digest; a local pseudo RepoDigest is not production provenance.

## Verification

- New operator, Compose validator, CLI, and audit statement coverage: 100%.
- New operator, Compose validator, CLI, and audit branch coverage: 100%.
- Deterministic audit: 9/9 checks, 5 services, 5 archives.
- Actual Compose check: PostgreSQL 16, 3 tools, 2 credential sources.

## Handoff

Slice 1451 uses all five real test databases as read-only sources, restores
into an isolated PostgreSQL 16 cluster, and performs an actual base-backup/WAL
PITR rehearsal with zero source mutation and zero process residue.
