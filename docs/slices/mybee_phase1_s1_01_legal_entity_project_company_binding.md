# MyBee Phase-1 S1-01: LegalEntity and ProjectCompanyBinding

## Scope

S1-01 adds the EOS accounting-company master and the effective-dated binding
between a real EOS Project and one accounting company. Existing `eos_project`
ownership and behavior remain unchanged; company ownership is an additive,
tenant-qualified overlay.

The Slice closes `SRS-MST-001`, `SRS-MST-002`, `SRS-MST-004`, and
`SRS-SEC-009` for the frozen Phase-1 boundary.

## Persistence Decisions

- `eos_legal_entity` owns company code, currencies, business timezone, status,
  recognition date, and immutable starting version.
- `eos_project_company_binding` uses half-open periods
  `[valid_from, valid_until)`. Adjacent periods are valid; overlapping
  `APPROVED` periods for the same tenant and Project are rejected.
- Both foreign keys include `tenant_id`. A synthetic or cross-tenant Project
  cannot satisfy the binding contract.
- Product writes serialize on a PostgreSQL advisory transaction lock scoped by
  tenant and Project. The database trigger is a second overlap guard.
- An exact replay of the same `binding_id` and semantics is idempotent;
  identity drift is a conflict.
- A LegalEntity must already be active and effective at the binding start.
- LegalEntity creation is a controlled repository/seed boundary in S1-01.
  Currency or version revision policy is not guessed by an unapproved update
  endpoint.

## API And Trust Boundary

| Operation | Route | Fresh OA scope |
| --- | --- | --- |
| `FINANCE.LEGAL_ENTITY.GET` | `GET /internal/v2/finance/legal-entities/{company_id}` | `finance:company:read` |
| `PROJECT.COMPANY_BINDING.CREATE` | `POST /internal/v2/projects/{project_id}/company-bindings` | `project:company-binding:manage` |
| `PROJECT.COMPANY_BINDING.GET` | `GET /internal/v2/projects/{project_id}/company-binding` | `project:company-binding:read` |

All routes first require an admitted `service:call` token for `nex-eos`, then
fresh OA authority in the same tenant and subject scope. Missing, inactive,
cross-tenant, malformed, or unavailable authorization fails closed.

The canonical NSL boundary is `READ: FINANCE.LEGAL_ENTITY.GET`. This Slice
publishes the semantic EOS operation and OpenAPI contract; it does not activate
a new Skill artifact or admit company-binding writes through NSL.

## Verification

Final Slice evidence:

```text
focused regression: 35 passed, 1 protected PostgreSQL test deselected
focused module coverage: 97% legal_entities.py, 100% legal_entity_api.py
actual PostgreSQL protected smoke: 36 passed
actual database identity: nex_eos_test / nex_eos_user
public-schema migration: 2516_eos_legal_entity_project_binding applied
protected temporary-schema migration/FK/overlap/zero-residue: PASS
public-schema post-smoke row counts: legal_entity=0, binding=0
EOS Slice Gate: 786 passed, 23 explicit protected skips
EOS statement coverage: 95.73% (threshold 95.00%)
EOS branch coverage: 94.24% (threshold 94.00%)
contract validation: PASS (233 schemas / 292 examples / 245 negative examples / 10 OpenAPI)
Golden transition audit: PASS
product dependency audit: PASS
remote provider requirement: NONE
```

The Slice Gate skips are existing opt-in topology, trust, migration, and
cross-service smokes. The S1-01 PostgreSQL test was separately enabled and
executed against the actual EOS test database; it was not reported as skipped.
