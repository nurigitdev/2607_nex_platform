# Slice 1209: OA projection and privacy refactoring checkpoint

## Scope

This Slice repairs current-state metadata and one cross-service privacy boundary
identified by the S121 audits. It does not add routes, change database schema, or
alter authentication enforcement.

## Decision

- Subject and membership snapshots now report the implemented OA password-login
  and session-issuance capabilities as current.
- The OA auth boundary now names session issuance, introspection, and employee
  password verification as current OA responsibilities.
- OA session metadata reports the implemented AE facade delegation.
- Subject resolver transport failures expose a stable public error instead of
  the underlying HTTP client exception.
- Subject snapshot schema and example remain aligned with the runtime projection.
- Production service-token, route-scope, browser-default, and resilience gaps
  remain explicitly deferred to targeted hardening after S121.

## Evidence

```bash
./.venv/bin/python \
  scripts/smoke/run_oa_projection_privacy_refactor_checkpoint.py --summary

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_projection_privacy_refactor_checkpoint.py \
  --test tests/test_nex_runtime_subject_resolver.py \
  --coverage-target services/nex-oa/nex_oa/projection_privacy_checkpoint.py \
  --coverage-target scripts/smoke/run_oa_projection_privacy_refactor_checkpoint.py \
  --smoke scripts/smoke/run_oa_projection_privacy_refactor_checkpoint.py
```

The next Slice must connect to the actual `nex_oa_test` PostgreSQL database and
re-audit migrations plus identity, membership, credential, and session behavior.
