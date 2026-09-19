# Slice 0870: S87 AG audit integrity and evidence closure

## Goal

Close S87 by proving the audit integrity, correlation, redacted package,
protected API, operations, contract, PostgreSQL, privacy, and runbook surfaces
as one coherent capability.

## Closed Boundary

- Owner: NeX-AG.
- Source tables: existing `service_operational_events` and `ag_ev_exports`.
- Verification: read-only, deterministic canonical JSON plus SHA-256.
- Correlation: event, trace, request, subject, and evidence-export continuity.
- Package: redacted references, hashes, counts, timestamps, and status only.
- API: protected server-side selection, package generation, and verification.
- Operations: dedicated projection plus unified dashboard section.
- Contract: strict JSON Schema, OpenAPI, positive fixtures, and negative privacy
  fixtures.
- PostgreSQL: actual `nex_ag_test` migration, insert/select, package/verify,
  operations read, and zero-row cleanup evidence.
- Failure response: tampered packages are rejected without echoing raw payloads
  or untrusted identifiers.

No new table, index, external signature service, or distributed transaction was
introduced for S87. Retention and archive remain assigned to S89.

## Verification

The protected default closure keeps PostgreSQL disabled and relies on the
recorded Slice 0868 live evidence:

```bash
./.venv/bin/python \
  scripts/smoke/run_s87_ag_audit_integrity_evidence_closure.py \
  --summary
```

For an actual test-database closure run:

```bash
NEX_AG_AUDIT_EVIDENCE_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL=postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test \
./.venv/bin/python \
  scripts/smoke/run_s87_ag_audit_integrity_evidence_closure.py \
  --summary
```

Observed protected default closure:

```text
s87_ag_audit_integrity_evidence_closure=pass slice_range=0861-0870 contracts=PASS postgres=SKIPPED privacy=PASS
```

Observed actual `nex_ag_test` closure:

```text
s87_ag_audit_integrity_evidence_closure=pass slice_range=0861-0870 contracts=PASS postgres=PASS privacy=PASS
```

The direct post-closure cleanup query returned:

```text
nex_ag_test|0|0
```

The closure runner validated every contract schema, positive fixture, negative
fixture, and OpenAPI document; regenerated a verified in-memory package; reran
the privacy/tamper evidence; and confirmed the recorded PostgreSQL evidence.

The Slice 0870 closure runner tests completed with `10 passed` and 100% statement
and branch coverage for the runner. The complete S87 focused suite completed
with `126 passed`; all eight measured S87 modules retained 100% statement and
branch coverage.

The aggregate regression suite completed with `5909 passed` and one known
Starlette `TestClient` deprecation warning. Aggregate coverage was:

```text
statement=72830/73711=98.804791686451%
branch=17082/17732=96.334310850440%
```
