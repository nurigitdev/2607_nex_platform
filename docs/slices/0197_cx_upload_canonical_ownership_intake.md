# Slice 0197: CX Upload Canonical Ownership Intake

## Scope

Slice 0197 updates the CX upload registration boundary so `nex-cx` consumes
canonical OA ownership refs directly instead of treating them as AE-only
metadata.

Implemented:

- `build_upload_ownership_ref()` in CX ingestion.
- upload registration records now always include `ownership_ref`.
- `ownership_ref`, direct subject refs, and legacy aliases are normalized to
  the same canonical shape.
- canonical refs and legacy aliases are rejected when they disagree.
- `uploaded_by_subject_ref` is propagated into content object and owner ACL
  metadata through the existing repository adapter.
- `cx_upload_registration.v1` contract, example, negative fixture, and OpenAPI
  request shape now document canonical ownership intake.

## Compatibility

CX still accepts the mock-first legacy aliases:

```text
tenant_id
owner_user_id
user_id
uploaded_by_user_id
```

When canonical refs are supplied, CX derives the compatibility fields from:

```text
ownership_ref.tenant_ref.id
ownership_ref.owner_subject_ref.id
ownership_ref.uploaded_by_subject_ref.id
```

Same-owner duplicate detection remains scoped to tenant, owner subject, and
`source_sha256`; different owners can upload the same source hash without
learning about each other.

## Privacy Boundary

Ownership metadata stores only stable OA subject ref types and IDs plus legacy
compatibility aliases. CX rejects unsupported ownership envelope fields and
subject-ref fields, preventing passwords, tokens, emails, raw identity profiles,
or other private identity payloads from entering upload ownership metadata.

## Next Slice

Recommended next slice:

- `0198_oa_subject_registry_resolver_client`

That slice should add a small OA resolver/verification client so AE/CX can
resolve or validate stable OA subject refs before live authentication and role
policy integration.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_ingestion.py tests/test_contract_validation.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
