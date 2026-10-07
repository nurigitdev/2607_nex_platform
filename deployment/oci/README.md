# OCI Build Definitions

The two Containerfiles define six immutable artifact targets. They are built
only from contexts materialized by the owner allowlist in
`nex_runtime.deployment_oci`; the repository root is not an admitted build
context.

| Containerfile | Targets |
| --- | --- |
| `python-service.Containerfile` | `oa-runtime`, `ae-runtime`, `cx-runtime`, `mo-runtime`, `ag-runtime` |
| `ae-web.Containerfile` | `ae-web` |

Both base images are pinned by OCI index digest. Python dependencies use the
hash-pinned production lock with `--no-deps --require-hashes`; AE Web uses
`npm ci --omit=dev`. Final processes run as non-root users.

Each image target defaults to its API or Web packaged command. Worker and
daemon deployments reuse the owning Python target and override the command
with `python -m nex_runtime.background_process <process-id> --profile
<profile>`. The typed packaged-entrypoint catalog is the authority for those
overrides; `scripts/dev` is not required inside an image.

Build context materialization is deterministic and fails when the destination
already exists. Generated contexts and local OCI outputs belong under
`reports/` and are not committed.
