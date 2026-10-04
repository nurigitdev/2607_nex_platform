# Slice 1301: S130 OA MVP platform trust closure

## Outcome

- Added an opt-in closure runner that executes only inside the explicit S130
  Full Gate context.
- Made the closure runner the final command in the repository Full Gate so an
  8/8 decision is emitted only after regression, coverage, contracts, and all
  preceding smoke commands succeed.
- Re-executes the integrated actual-PostgreSQL acceptance and requires four
  durable workflows, all seven pre-Full-Gate artifacts, current migrations,
  and zero cleanup residue.
- Closes OA-FR-001 through OA-FR-005 at repository MVP acceptance level while
  preserving KMS/Vault/PKCS#11, TLS, secret injection, and external IdP work as
  deployment requirements.
- Leaves S131 scope pending user review.

## Full Gate

```bash
NEX_S130_FULL_GATE_CONTEXT=1 \
NEX_OA_MVP_ACCEPTANCE_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test' \
./scripts/quality/run_quality_gate.sh
```

No remote model provider is required. The database URL remains local process
configuration and is never written to committed evidence without redaction.

## Verified evidence

- Full Gate exit: `0`; pytest collected `10,886` tests and completed without a
  failure (`10,864` passed, `22` protected tests skipped).
- Coverage: statement `98.37%` and branch `97.12%`, above the repository
  thresholds of `95%` and `94%`.
- Contract validation: `156` schemas, `214` positive examples, `184` negative
  examples, and `7` OpenAPI documents.
- Actual `nex_oa_test` workflows: identity/session/authorization restart,
  signing-key rotation with JWKS overlap, revocation/introspection across
  restart, and AE/CX/MO/AG signed-only protected-route trust.
- Final acceptance: `checks=9/9`, `gates=8/8`, `postgres=4`, and
  `residue=0`.

This closes repository-level OA MVP and platform trust acceptance. Production
activation still requires external key custody, TLS, secret injection, and
external IdP deployment controls; those controls are intentionally not claimed
by this closure.
