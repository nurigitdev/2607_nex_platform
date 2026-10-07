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

Build context materialization is deterministic and fails when the destination
already exists. Generated contexts and local OCI outputs belong under
`reports/` and are not committed.

