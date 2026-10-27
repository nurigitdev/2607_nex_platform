# P9-S07: WA Protected Durable Intake API

## Scope

P9-S07 activates the thin NeX-WA source-inspection admission endpoint:

```text
POST /internal/v1/evidence-intake
```

The endpoint validates a bounded reference notification and returns only after
the existing service-local `SqlAlchemyJobQueue` has durably stored the
`WA_EVIDENCE_INGEST` Job. It does not fetch source content, normalize evidence,
call OA/EOS, or create WorkEvidence/WorkAsset rows inline.

## Trust Boundary

Admission requires all of:

```text
audience          = nex-wa
service scope     = service:call
business scope    = work:evidence:ingest
caller service    = nex-ae-api
route class       = WRITE
```

Wrong audience, caller, or scope fails before queue mutation. Transport-derived
request and trace references replace body-provided values before persistence.

## Durable Enqueue

`WaEvidenceIntakeService` composes the P9-S06 deterministic identity with the
shared common Job contract:

```text
job_type     = WA_EVIDENCE_INGEST
status       = QUEUED
max_attempts = 5
subject      = SERVICE / nex-ae-api
payload      = bounded source refs, hash, and trace metadata only
```

Exact replay returns the existing Job with `idempotent_reuse=true`. Reusing the
same source identity with another source hash returns
`WA_SOURCE_IDEMPOTENCY_CONFLICT`. Queue failures and corrupt stored payloads
fail closed through redacted typed errors.

## Actual PostgreSQL Evidence

The protected smoke used the actual `nex_wa_test` database and `nex_wa_user`
role after applying current migrations. It proved:

```text
mock signed service admission       = PASS
HTTP 202 after durable commit       = PASS
service_jobs row readback           = PASS
exact replay reuse                  = PASS
same identity / changed hash reject = PASS
reference-only JSONB payload        = PASS
post-smoke zero residue             = PASS
```

## Quality Evidence

```text
focused API/SQLite regression = 12 passed
actual PostgreSQL smoke       = 1 passed
P9-S07 Slice Gate             = 124 passed, 4 skipped
Slice statement coverage      = 99.66%
Slice branch coverage         = 98.05%
intake/API module coverage    = 100.00%
contract validation           = PASS
```

The four skipped tests are the earlier protected P9-S02 through P9-S05 smokes;
P9-S07's protected PostgreSQL smoke was explicitly enabled and executed.

## Exit

```text
protected thin intake API = PASS
durable enqueue           = PASS
semantic replay/conflict  = PASS
database failure redaction= PASS
bounded p95 unit baseline = PASS (< 20 ms)
next Slice                = P9-S08
```
