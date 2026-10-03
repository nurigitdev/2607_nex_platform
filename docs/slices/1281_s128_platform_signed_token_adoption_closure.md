# Slice 1281: S128 platform signed-token adoption closure

## Closure

S128 closes platform-wide `service_access` signed-token verification adoption:

- The shared runtime validates RS256 signatures and strict service claims from
  bounded OA JWKS state without reading the OA database.
- Shared FastAPI admission supports explicit `TEST_MOCK`, `DUAL_READ`, and
  `SIGNED_ONLY` profiles. Sensitive writes require bounded OA introspection.
- AE, CX, MO, and AG use the shared admission boundary while preserving their
  existing browser-user or administrator paths.
- Outbound service clients fail closed when signed credentials are absent;
  silent mock fallback is forbidden.
- Protected rollout counters and JWKS cache state expose no raw token, JTI,
  credential, key identifier, authorization header, or private key material.
- Actual `nex_oa_test` evidence covers all 16 migrations, four audience-bound
  tokens, all four consumer loopbacks, mock rejection, and zero residue.

## Deployment boundary

The implementation is ready for production `SIGNED_ONLY` activation, but the
activation remains explicit deployment profile configuration. S128 does not
silently change every environment from `TEST_MOCK` or `DUAL_READ`.
`delegated_user_access` remains deferred, no new database table was created,
and DGX model providers are unrelated.

The S129 scope remains pending canonical review rather than being inferred by
this closure.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_s128_platform_signed_token_adoption_closure.py --summary

./scripts/quality/run_quality_gate.sh
```

The Full Gate is the authoritative S128 regression, statement/branch coverage,
contract, privacy, and closure result.

Observed on 2026-10-04:

- Python regression: `10,662 passed, 18 skipped`
- Coverage: statement `98.38%`, branch `97.08%`
- AE Web regression: `293/293` passed
- Contract validation: `152` schemas, `210` positive examples, `180`
  negative examples, and `7` OpenAPI documents
- S128 closure: `9/9` evidence items, `5/5` components, and all four
  signed-token consumers passed
- Actual `nex_oa_test` proof from Slice 1280: `16/16` migrations, four
  audience-bound tokens, four consumer acceptances, mock rejection, and zero
  cleanup residue

The Full Gate detected that MO's new service-token runtime route was missing
from its OpenAPI document. The contract was completed and the restarted gate
proved `30/30` runtime/OpenAPI operations, `26/26` protected operations, and
zero drift.
