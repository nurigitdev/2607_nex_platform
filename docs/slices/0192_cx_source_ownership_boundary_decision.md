# Slice 0192: CX Source Ownership Boundary Decision

## Scope

Slice 0192 freezes the ownership boundary for CX source uploads before adding
more durable schema around owner-scoped duplicate detection.

Implemented:

- `nex_cx.source_ownership`
- `cx_source_ownership_boundary_decision.v1` contract schema
- positive contract example for the ownership decision
- persistence audit wiring for the ownership boundary decision
- CX/OA README updates describing the minimum OA subject dependency
- regression tests for legacy owner-field mapping, dedupe keys, invalid owner
  values, and private identity payload guards

## Decision

`cx_source_files` remains global source-byte metadata keyed by `source_sha256`.
It should not own user identity and should not store raw source bytes in
PostgreSQL.

Logical document ownership belongs to content/ACL rows. The future canonical
dedupe key is:

```text
tenant_ref.id + owner_subject_ref.id + source_sha256
```

The current `tenant_id + owner_user_id + source_sha256` behavior remains a
compatibility key until migration. `tenant_id` maps to `tenant_ref.id`, and
`owner_user_id` maps to `owner_subject_ref.id`.

## OA Position

The user question was whether `nex-oa` should implement at least a unique
account id. The decision is yes.

Before CX adds durable owner subject columns, `nex-oa` should provide a minimum
stable subject registry:

- `{type: "oa.tenant", id: "..."}`
- `{type: "oa.user", id: "..."}`
- status/display metadata for local development and downstream references

Password login, external identity providers, role management, and full user
profiles remain deferred.

## Next Slice

Recommended next slice:

- `0193_nex_oa_subject_registry_foundation`

After that, continue with:

- `0194_cx_source_ownership_schema_migration`
- `0195_cx_owner_scoped_repository_api_wiring`
- `0196_ae_upload_ownership_propagation_contract`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_source_ownership.py tests/test_nex_cx_persistence_audit.py tests/test_nex_cx_processing_persistence.py tests/test_contract_validation.py -q
```

Observed targeted result:

```text
33 passed
```

Contract validation:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Observed contract result:

```text
contract_validation=pass schemas=43 examples=72 negative_examples=49 openapi=7
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed full quality result:

```text
1463 passed
statement_coverage=98.03% threshold=95.00%
branch_coverage=93.51% threshold=85.00%
contract_validation=pass schemas=43 examples=72 negative_examples=49 openapi=7
```
