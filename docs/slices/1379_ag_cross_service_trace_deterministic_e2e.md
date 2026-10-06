# Slice 1379: AG Cross-Service Trace Deterministic E2E

## Goal

Prove the S138 success, partial-source failure, privacy, and persistence-restart
behaviors without depending on live service databases or remote model
providers.

## Implementation

- Added fixed OA, AE, CX, and MO source projections spanning all eight
  canonical stage families once the AG audit stage is attached.
- Verified that repeated aggregation with fixed inputs produces the exact same
  source timeline and ordering.
- Simulated an MO timeout and retained the healthy OA, AE, and CX stages while
  returning one bounded `UNAVAILABLE` diagnostic.
- Injected an unexpected private prompt field into a CX source response and
  proved fail-closed contract rejection without copying that field into AG.
- Persisted AG trace-read audit events in a file-backed SQLite regression
  database, disposed the engine, rebuilt the repository, and verified readback
  plus a successful post-restart append.
- Reused `service_operational_events`; no schema or production runtime change
  was required.

Actual service test PostgreSQL and service API process evidence remains in
Slice 1380. Remote embedding, reranking, and generation providers are not
required solely to reconstruct the already accepted trace.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-ag \
  --test tests/test_ag_cross_service_trace_deterministic_e2e.py \
  --test tests/test_nex_ag_cross_service_trace.py \
  --coverage-target scripts/smoke/run_ag_cross_service_trace_deterministic_e2e.py \
  --coverage-target services/nex-ag/nex_ag/cross_service_trace.py \
  --smoke scripts/smoke/run_ag_cross_service_trace_deterministic_e2e.py
```

Expected evidence is `checks=16/16`, `families=8`,
`partial_diagnostics=1`, `restart_audits=2`, and `next=1380`.

Observed evidence:

- regression: `2474 passed`
- statement coverage: `98.88%`
- branch coverage: `96.48%`
- deterministic E2E runner: statement `98.33%`, branch `100.00%`
- AG trace runtime: statement `100.00%`, branch `100.00%`
- contract validation: `166` schemas, `228` examples, `196` negative
  examples, `7` OpenAPI documents
- smoke: `checks=16/16`, `families=8`, `partial_diagnostics=1`,
  `restart_audits=2`, `next=1380`
