# Platform OA-Backed Trust Operations

## Preconditions

- Run only against the five service-owned `*_test` databases.
- Confirm `NEX_OA_TEST_DATABASE_URL`, `NEX_AE_TEST_DATABASE_URL`,
  `NEX_CX_TEST_DATABASE_URL`, `NEX_MO_TEST_DATABASE_URL`, and
  `NEX_AG_TEST_DATABASE_URL` are supplied through the operator environment.
- Confirm no platform API process is already bound to the selected loopback
  ports. The runner allocates fresh ports and does not contact model providers.
- Do not enable the file signer outside `NEX_PROFILE=test`. The runner creates
  its temporary 3072-bit RSA PEM under `/tmp`, applies mode `0600`, and removes
  the directory in its finalizer.

## Protected Command

```bash
export NEX_PLATFORM_OA_BACKED_TRUST_POSTGRES_SMOKE=1
./.venv/bin/python scripts/smoke/run_platform_oa_backed_trust_postgres_smoke.py --summary
```

Database values must come from the operator's secret environment. Never place
credentials, private key material, browser session identifiers, client
credentials, or signed bearer values in the command, repository, evidence, or
incident notes.

## Expected Evidence

The success summary is:

```text
platform_oa_backed_trust_postgres=pass hops=5/5 denials=4/4 databases=5 residue=0 next=1340
```

The five hops are OA credential login, AE opaque browser session, CX, MO, and
AG signed service admission. The denial inventory is wrong audience, missing
scope, revoked user session, and revoked service token. A pass also means two
fresh process generations restored the user session and signing key and kept
the revocation decision effective.

## Failure Triage

1. `configuration_invalid` or an early `execution_failed` result: verify all
   five test database targets, roles, migration permissions, and loopback port
   availability. Do not substitute a development or production database.
2. Readiness timeout: inspect the affected service process locally, confirm its
   test database identity and migration head, then stop the run. Do not bypass
   readiness or switch to memory persistence.
3. Login failure: verify only the temporary S134 tenant, membership, and local
   credential seed. Do not log submitted employee credentials.
4. JWKS or introspection failure: keep `SIGNED_ONLY`; verify OA starts first,
   the temporary public key is published, and each process has its own
   audience-bound introspection credential. Never fall back to mock claims.
5. Denial mismatch: treat any accepted wrong-audience, missing-scope, revoked
   session, or revoked service token request as a blocking security failure.

## Cleanup Verification

The runner stops processes in reverse order and invokes OA row cleanup and
temporary-directory removal from `finally`, including failed executions.
After a run, use a trusted database console to confirm the following counts are
zero without selecting secret-bearing columns:

```sql
SELECT count(*) FROM oa_tenants WHERE tenant_id LIKE 'tenant-s134-%';
SELECT count(*) FROM oa_service_principals WHERE principal_id LIKE '%-s134-%';
SELECT count(*) FROM oa_signing_keys WHERE key_id LIKE 'key-s134-%';
SELECT count(*) FROM oa_auth_events WHERE request_id LIKE 's134-%';
SELECT count(*) FROM service_operational_events WHERE request_id LIKE 's134-%';
```

Also confirm no `/tmp/nex-s134-*` directory remains. If cleanup is incomplete,
keep the environment isolated, stop all five smoke processes, and remove only
rows carrying the unique S134 run prefix after peer review.

## Rollback And Fail-Closed

- Stop AE, AG, CX, MO, then OA. Do not restart a consumer while OA trust
  metadata is inconsistent.
- Keep the default OA signer `UNAVAILABLE`; `TEST_FILE` is an explicit,
  temporary test-only override.
- Keep consumer rollout at `SIGNED_ONLY`. A JWKS or introspection outage must
  return `503`; an invalid, unauthorized, or revoked claim must return `401` or
  `403`.
- Remove the temporary signer directory and S134-prefixed rows before retrying.

## Secret Handling

Evidence may contain service ids, status codes, reason codes, request ids,
trace ids, migration counts, and residue counts. It must not contain bearer
values, browser session identifiers, local employee credentials, client
credentials, database connection values, private key references, or PEM data.

## Remote Provider Boundary

Embedding, reranking, and generation providers are outside S134. Provider URLs,
keys, model aliases, and DGX connectivity are neither required nor exercised by
this runbook.
