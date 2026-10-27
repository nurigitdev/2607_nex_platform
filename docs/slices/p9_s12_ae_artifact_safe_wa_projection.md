# P9-S12: AE Artifact Safe WA Projection

## Scope

P9-S12 exposes an exact authoritative AE Artifact version to NeX-WA without
copying bytes, rendered text, storage references, links, or files. It reuses
`ae_artifacts`, `ae_artifact_source_refs`, and `ae_artifact_versions`; no
migration or WA-owned source identity is introduced.

## Boundary

```text
GET /internal/v1/wa-sources/artifacts/{artifact_id}/versions/{artifact_version_id}
caller = nex-wa
audience = nex-ae-api
scopes = service:call + work:source:read
tenant = X-NeX-Tenant-Id
```

Only `READY` Artifacts are projected. The exact version must belong to the
requested Artifact and its source hash must match authoritative source-ref
lineage. Because the current AE Artifact source has no compatible explicit
classification, the P9 contract default is `CONFIDENTIAL`.

`producer_execution_ref` remains null unless AE has an explicit, persisted
AgentExecution reference. A CX generation ID is not treated as equivalent.
Human ownership and Agent production therefore remain separate claims.

## Verification

Focused tests cover exact version selection, status/hash/version rejection,
Human ownership, explicit Agent producer lineage, tenant isolation, service
authorization, unavailable persistence, and raw-content/byte exclusion.

```text
S11/S12 focused tests     = 28 passed
NeX-AE Slice Gate         = 5,583 passed, 44 skipped
AE statement coverage     = 97.36%
AE branch coverage        = 95.69%
projection statement      = 99.31%
projection branch         = 98.08%
contract validation       = 216 schemas / 280 examples / 235 negatives / 10 OpenAPI
ruff                      = PASS
```
