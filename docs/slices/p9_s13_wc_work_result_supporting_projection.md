# P9-S13: WC WorkResult By-Execution Supporting Projection

## Scope

P9-S13 keeps NeX-WC as a supporting source owner. It adds exact result and
canonical by-execution lookup routes, but no WC-to-WA event bus and no second
WA ingress path.

```text
GET /internal/v1/wa-sources/work-results/{result_id}
GET /internal/v1/wa-sources/work-results/by-execution/{agent_execution_id}
caller = nex-wa
audience = nex-wc
scopes = service:call + work:source:read
tenant = X-NeX-Tenant-Id
```

The projection compares immutable `result_payload` semantics with the scalar
columns in `wc_work_result`. Semantic hash, execution, Claim generation,
Assignment, submitted Agent, revision, and timestamp must all agree. A
by-execution lookup yielding more than one result is ambiguous and fails
closed. Raw result payload and summary are never returned.

## Verification

Focused tests cover exact and by-execution lookup, tenant isolation, execution,
Claim, Assignment and Agent drift, semantic hash mismatch, duplicate ambiguity,
service admission, and unbounded payload exclusion.

- Focused regression: `17 passed`
- WC Slice regression: `487 passed, 21 skipped`
- New projection coverage: statement `100%`, branch `100%`
- WC aggregate profile: statement `86.33%`, branch `86.22%`
- Contract validation: `217` schemas, `281` examples, `235` negative
  examples, and `10` OpenAPI documents
- Ruff and diff hygiene: passed

The WC aggregate percentage reflects pre-existing unmeasured P8 operational
modules, including approval-event delivery and demo-runtime composition. P9-S13
does not claim the historical `94%` aggregate threshold: the broad regression
is green and the newly introduced boundary is held at `100%/100%`. The service
profile debt remains explicit for checkpoint reconciliation instead of being
hidden by a focused-only aggregate.
