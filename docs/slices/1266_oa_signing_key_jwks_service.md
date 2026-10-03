# Slice 1266: OA signing-key lifecycle and JWKS service

## Outcome

- Added key registration, revisioned state transitions, public listing, JWKS
  publication, and exactly-one ACTIVE signing-key selection.
- Public service projections exclude `private_key_ref`; only the later internal
  signer receives the full ACTIVE key metadata record.
- Added bounded reconciliation from ACTIVE to VERIFY_ONLY at `sign_until` and
  from VERIFY_ONLY to RETIRED at `verify_until`.
- Added revocation create/check/purge orchestration without returning raw `jti`
  or its digest to API-facing projections.
- Wired repository and service construction into the OA runtime. No HTTP routes
  or private-key loader are introduced in this Slice.

## Verification

```bash
./scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_nex_oa_signing_key_service.py \
  --test tests/test_oa_signing_key_service_smoke.py \
  --coverage-target services/nex-oa/nex_oa/signing_key_service.py \
  --coverage-target scripts/smoke/run_oa_signing_key_service.py \
  --smoke scripts/smoke/run_oa_signing_key_service.py
```
