# Slice 1300: S130 OA MVP platform trust acceptance

## Outcome

- Added one protected integrated acceptance runner for OA-FR-001 through
  OA-FR-005.
- Re-executes policy/traceability, signed-token failure audit, contract/privacy
  evidence, and four actual PostgreSQL workflows for identity restart, key
  rotation, revocation restart, and cross-service SIGNED_ONLY admission.
- Requires every PostgreSQL artifact to target `nex_oa_user@nex_oa_test`, use
  the current 17-migration inventory, and report zero cleanup residue.
- Requires identity readback, two-key JWKS overlap, two revocation restarts,
  four accepted consumers, and four post-revocation denials.
- Produces the deliberate pre-closure state `7/8`: every acceptance gate except
  the final Full Gate is satisfied. A skip or any other missing gate fails the
  Slice.

## Protected execution

```bash
NEX_OA_MVP_ACCEPTANCE_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test' \
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_s130_oa_mvp_platform_trust_acceptance.py \
  --coverage-target scripts/smoke/run_s130_oa_mvp_platform_trust_acceptance.py \
  --smoke scripts/smoke/run_s130_oa_mvp_platform_trust_acceptance.py
```

The database URL is supplied only through the local environment. No remote
model provider is involved in OA trust acceptance.

## Verified evidence

- Acceptance artifacts passed: `7/7`
- Actual PostgreSQL workflows: `4`
- Pre-closure gates: `7/8`; only `full_gate` remains
- Cleanup residue: `0`
- Slice Gate: `941 passed`, `11 skipped`
- Coverage: statement `98.50%`, branch `98.02%`
- Integrated runner coverage: statement `100.00%`, branch `100.00%`
- Contract validation: `156` schemas, `214` examples, `184` negative examples,
  `7` OpenAPI documents
