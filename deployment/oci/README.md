# OCI Build Definitions

The two Containerfiles define six immutable artifact targets. They are built
only from contexts materialized by the owner allowlist in
`nex_runtime.deployment_oci`; the repository root is not an admitted build
context.

| Containerfile | Targets |
| --- | --- |
| `python-service.Containerfile` | `oa-runtime`, `ae-runtime`, `cx-runtime`, `mo-runtime`, `ag-runtime` |
| `ae-web.Containerfile` | `ae-web` |

Both runtime base images are pinned by OCI index digest. Python dependencies
use the hash-pinned production lock with `--no-deps --require-hashes`. Native
Python wheels, including MeCab's Rust extension, are built in digest-pinned
full Python and Rust stages. The slim runtime installs only those wheels with
`--no-index --no-deps`, so compilers and the Rust toolchain do not enter the
final five Python images. AE Web uses `npm ci --omit=dev`. Final processes run
as non-root users.

Each image target defaults to its API or Web packaged command. API image
commands bind to `0.0.0.0`, independently of the loopback host used by local
process orchestration. AE Web clears the Node base image entrypoint and uses
the exact packaged npm command. Worker and daemon deployments reuse the owning
Python target and override the command with `python -m
nex_runtime.background_process <process-id> --profile <profile>`. The typed
packaged-entrypoint catalog is the authority for those overrides;
`scripts/dev` is not required inside an image.

Build context materialization is deterministic and fails when the destination
already exists. Generated contexts and local OCI outputs belong under
`reports/` and are not committed.

## PostgreSQL Recovery Tool

`postgres-operator.Containerfile` is a separately versioned operations tool,
not a seventh application release artifact. It combines a registry-published,
immutable NeX Python runtime input with the digest-pinned PostgreSQL 16.9 image
and copies only shared runtime code, database scripts, and S145 policy. It runs
as UID/GID 65532 and is admitted only by the opt-in `postgres-operations`
Compose profile.

A local S145 rehearsal may use an inspected local Python runtime tag because
S142 deliberately did not push images. Production provenance must supply a
registry-resolvable immutable Python runtime digest; a local pseudo RepoDigest
is not accepted as registry evidence.
