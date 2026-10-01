# Slice 1208: OA cross-service trust coupling audit

## Goal

Audit how AE, CX, and shared service-auth code depend on OA before production
identity hardening begins.

## Result

- AE user-session/login and CX subject-resolution calls use explicit HTTP
  adapters with bounded timeouts and request/trace propagation.
- AE derives tenant/owner scope from authenticated claims rather than browser
  payload fields. Direct cross-service database reads remain forbidden.
- Both adapters silently issue unsigned mock service tokens when a configured
  token is absent. Production-like profiles must fail closed instead.
- OA internal routes all rely on the generic `service:call` scope. Route- or
  capability-specific service authorization is absent.
- Subject resolver transport failures can expose `str(httpx error)` details,
  which may include endpoint information.
- Timeouts exist, but a shared retry/circuit/admission policy is not composed.
- AE defaults to mock session mode and emits a cookie with `secure=false`;
  production profile validation is required before browser auth activation.
- The five refactors, including two high-risk trust items, are ordered S122+
  inputs. No database table or route is added here.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_oa_trust_coupling_audit.py --summary

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_trust_coupling_audit.py \
  --coverage-target services/nex-oa/nex_oa/trust_coupling_audit.py \
  --coverage-target scripts/smoke/run_oa_trust_coupling_audit.py \
  --smoke scripts/smoke/run_oa_trust_coupling_audit.py
```
