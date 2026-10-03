# Slice 1235: OA durable authorization repository

## Result

- Added one repository protocol for role, group, group-member, and group-role
  mutation plus authorization input and event reads.
- Memory and SQLAlchemy adapters share the Slice 1233 domain planners and
  optimistic revisions.
- SQL mutations write the authorization record and privacy-safe event in one
  transaction; stale revisions and unavailable persistence fail closed.
- Restart reads reconstruct JSON role scopes and metadata without private
  values.
- Tenant and subject filters are mandatory on authorization projections.
- Runtime construction chooses SQLAlchemy only for PostgreSQL mode and retains
  deterministic in-memory regression behavior.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_authorization_repository.py \
  --test tests/test_oa_authorization_repository.py \
  --coverage-target services/nex-oa/nex_oa/authorization_repository.py \
  --coverage-target scripts/smoke/run_oa_authorization_repository.py \
  --smoke scripts/smoke/run_oa_authorization_repository.py
```
