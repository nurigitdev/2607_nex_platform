# P8-S105: NVTProject Protected API, Authorization, and Contracts

## Scope

P8-S105 exposes the S104 NVTProject domain through the existing EOS governed
BusinessOperation boundary.

- `PROJECT.NVT_PROJECT.CREATE` requires fresh OA
  `project:nvt_project:create` authority.
- `PROJECT.NVT_PROJECT.GET` and `PROJECT.NVT_PROJECT.LIST` require fresh OA
  `project:nvt_project:read` authority.
- `PROJECT.NVT_PROJECT.UPDATE` requires fresh OA
  `project:nvt_project:admin` authority and optimistic `expected_version`.
- NVT reads intentionally do not require Project membership. NVTProject is a
  tenant catalog object, while tenant isolation and current OA authority remain
  mandatory.
- CREATE and UPDATE execute through EOS BusinessOperation, idempotency, and
  outbox state in the same database transaction as the NVT mutation.
- UPDATE admits only `name` and `status`; identity and code remain immutable.

## API And Contract

The protected service-token surface is:

```text
POST  /internal/v1/nvt-projects
GET   /internal/v1/nvt-projects
GET   /internal/v1/nvt-projects/{nvt_project_id}
PATCH /internal/v1/nvt-projects/{nvt_project_id}
```

The canonical JSON contracts are:

- `nvt_project_create_command.v1.schema.json`
- `nvt_project_update_command.v1.schema.json`

The EOS OpenAPI document records service trust, business scopes, pagination,
status filtering, immutable update shape, and fail-closed response classes.
The shared operation registry now admits all four NVT operation names and its
version advances from `p8-s97.v1` to `p8-s105.v1`.

P8-S105 does not add an EOS migration or an NSL artifact. Exact NSL source and
AE admission remain the responsibility of P8-S106.

## Verification

- focused governed NVT/Project/runtime regression: `57 passed`
- Ruff: passed for changed Python source and tests
- EOS Slice Gate plus shared registry coverage: `697 passed`, `21` expected
  protected skips
- combined statement coverage: `98.61%`
- combined branch coverage: `97.90%`
- shared operation registry statement coverage: `96.23%`; branch `100%`
- contract validation: `199` schemas, `263` examples, `225` negative examples,
  and `9` OpenAPI documents

The protected skips are pre-existing opt-in PostgreSQL profiles. No DDL was
changed in this Slice; actual multi-service PostgreSQL acceptance remains
assigned to P8-S112.

## Exit

P8-S105 is complete. P8-S106 may bind exact NSL READ/WRITE artifacts and AE
planning admission to these canonical operation and API identities.
