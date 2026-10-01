# Slice 1202: OA current-state re-audit boundary

## Goal

Start S121 by freezing the NeX-OA current-state re-audit boundary before adding
new identity, credential, token, or authorization behavior.

## Decision

- The audit covers `OA-FR-001` through `OA-FR-005`: bootstrap identity, user
  and service credentials, introspection/JWKS, claim references, and safe auth
  audit evidence.
- Existing employee-id/password login and opaque OA user-session introspection
  remain the compatibility baseline while the implementation is re-audited.
- Repository code, migrations, contracts, deterministic regression, and actual
  `nex_oa_test` PostgreSQL evidence are primary. DGX providers are outside the
  OA boundary and are not required for S121.
- Refactoring precedes feature work where evidence identifies oversized modules,
  duplicated security decisions, unsafe coupling, privacy leakage, or contract
  drift.
- Slice 1202 adds no table or migration and does not mutate OA records.
- Public signup, enterprise SSO/OIDC, MFA, email/SMS password recovery, and the
  production secret/key ceremony remain deferred.
- The tiered quality cadence is fixed: Slice Gate on every Slice, Checkpoint
  Gate at Slice 1206, and Full Gate at Slice 1211.

## Slice Plan

1. Slice 1202: current-state boundary audit.
2. Slice 1203: OA capability and requirement traceability inventory.
3. Slice 1204: persistence and migration drift audit.
4. Slice 1205: identity and membership lifecycle audit.
5. Slice 1206: credential/session security audit and Checkpoint Gate.
6. Slice 1207: API, OpenAPI, and contract drift audit.
7. Slice 1208: cross-service client and trust coupling audit.
8. Slice 1209: privacy and refactoring checkpoint.
9. Slice 1210: actual PostgreSQL current-state protected re-audit.
10. Slice 1211: S121 closure, Full Gate, and S122 handoff.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_oa_current_state_reaudit_boundary.py --summary

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_current_state_reaudit_boundary.py \
  --coverage-target scripts/smoke/run_oa_current_state_reaudit_boundary.py \
  --smoke scripts/smoke/run_oa_current_state_reaudit_boundary.py
```
