# Slice 1291: S129 federated authentication and AG integration closure

## Closure

- OA owns OIDC provider trust, exact external-subject digest links, strict
  RS256 ID-token validation, and canonical OA session issuance.
- AG consumes only the bounded OA-normalized operator context delivered by AE.
  It never receives an external token, validates an IdP assertion, or reads the
  OA database.
- Federated AG requests require the admitted AE service caller,
  `workspace:use`, and the `admin` role. Audit and telemetry remain aggregate
  and privacy-safe.
- Canonical OA/AG schemas, positive fixtures, privacy-negative fixtures,
  OpenAPI operations, runtime wiring, and actual PostgreSQL/TLS evidence are
  complete.
- S129 implementation readiness is `READY_FOR_S130`.

## Deployment boundary

- External IdP registration and secret custody require deployment
  configuration.
- Browser Authorization Code + PKCE redirect/callback integration requires the
  product's real IdP and browser environment.
- Live external IdP acceptance is a deployment-environment test, not a DGX
  model-provider test.
- SAML 2.0 and delegated-user service tokens remain explicitly deferred.

## Full Gate

```bash
NEX_OA_FEDERATED_POSTGRES_LOOPBACK_SMOKE=1 \
  ./scripts/quality/run_quality_gate.sh
```

Actual result:

- Python regression: `10,799 passed, 18 skipped`
- AE Web regression: `293 passed`
- Statement / branch coverage: `98.40%` / `97.12%`
- Contract validation: `156` schemas, `214` positive examples, `184`
  negative examples, and `7` OpenAPI documents
- PostgreSQL/TLS smoke: `17` migrations, `2` trusted TLS requests, `4`
  persisted row classes, and `0` cleanup residue
- Closure evidence: `9/9` evidence groups and `5/5` components passed
