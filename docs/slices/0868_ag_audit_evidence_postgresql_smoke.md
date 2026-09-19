# Slice 0868: AG audit evidence PostgreSQL smoke

## Objective

Prove the S87 audit integrity and evidence package flow against the actual
`nex_ag_test` PostgreSQL database without adding another persistence table.

## Smoke Flow

The opt-in runner:

1. runs all current `nex-ag` migrations;
2. requires the PostgreSQL backend and the exact `nex_ag_test` database;
3. persists one owned source event in `service_operational_events`;
4. persists one owned redacted export in `ag_ev_exports`;
5. calls the protected package creation route using only server-side selection;
6. calls the protected verification route with the generated package;
7. reads the protected audit-integrity operations projection;
8. directly selects the source, generated, verified, and export rows;
9. confirms that no `ag_audit_evidence_packages` table was introduced;
10. deletes the three owned events and one owned export, then confirms zero
    owned rows remain.

## Guardrails

- The runner is disabled unless `NEX_AG_AUDIT_EVIDENCE_POSTGRES_SMOKE=1`.
- The database URL is read only from `NEX_AG_TEST_DATABASE_URL` and is redacted
  from evidence.
- The package request cannot submit event or export bodies; source records are
  selected by the server using the unique smoke trace ID.
- Raw source messages, credentials, and export bodies are rejected from the
  serialized smoke evidence.
- Cleanup is bounded to the unique trace ID and export ID and runs after both
  success and failure.
- Existing `service_operational_events` and `ag_ev_exports` tables are reused.

## Command

```bash
NEX_AG_AUDIT_EVIDENCE_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL=postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test \
./.venv/bin/python scripts/smoke/run_ag_audit_evidence_postgres_smoke.py --summary
```

## Evidence

Observed protected result:

```text
ag_audit_evidence_postgres_smoke=pass database=nex_ag_test backend=postgresql events=3 exports=1 package_status=VERIFIED cleaned=True
```

The redacted JSON evidence confirmed:

- all 16 planned AG migrations were already applied and therefore skipped;
- `service_operational_events` and `ag_ev_exports` both existed;
- one source, one generated, and one verified event were directly selected;
- one hash-ready export was directly selected;
- the package manifest and package hashes verified successfully;
- the operations projection reported one generation and one verification;
- `ag_audit_evidence_packages` did not exist;
- cleanup deleted three events and one export with zero owned rows remaining.

A direct post-cleanup PostgreSQL query returned:

```text
nex_ag_test|service_operational_events|ag_ev_exports||0|0
```

- Smoke runner unit tests: `15 passed`.
- Smoke runner statement/branch coverage: `100% / 100%`.
- Full regression: `5892 passed, 1 warning`.
- Statement coverage: `72620 / 73501` (`98.801376852016%`).
- Branch coverage: `17066 / 17716` (`96.331000225785%`).

The warning is the existing Starlette `TestClient` deprecation warning.
