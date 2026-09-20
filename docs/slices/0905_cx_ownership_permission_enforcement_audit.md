# Slice 0905: CX ownership and permission enforcement audit

## Goal

Distinguish stored ownership metadata from effective authorization across CX
upload, document, processing, retrieval, and generation paths.

## Findings

- Upload intake validates canonical OA subject refs, but those refs are asserted
  by the trusted caller rather than bound to a user identity in the service
  claim.
- Document library, detail, and source materialization apply owner filters and
  collapse unauthorized/not-found responses, but the filter values are still
  caller asserted.
- Job/extraction, processing, retrieval-package read, and generation paths use
  service authorization plus resource identifiers without a common owner
  context.
- Retrieval records a permission snapshot, but `actor_claims_ref` is evidence,
  not authorization proof, and document scope is not filtered through ACLs.

The audit itself passes because all eight findings are backed by current source
evidence. Enforcement readiness is deliberately `GAPS_CONFIRMED`, with five
high-risk surfaces.

## Refactoring Decision

S92 should introduce one `CxAccessContext` at the service boundary. It must bind
caller service, OA tenant/subject refs, request id, and trace id; repository
queries and commands then consume that context. Jobs, processing runs, and
retrieval packages need owner refs sufficient for scoped reads. Route-specific
authorization patches are deferred to avoid inconsistent policy.

This slice adds no table or migration and changes no authorization behavior.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_cx_ownership_enforcement_audit.py --summary
./.venv/bin/pytest -q tests/test_cx_ownership_enforcement_audit.py \
  --cov=nex_cx.ownership_enforcement_audit \
  --cov=run_cx_ownership_enforcement_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
audit: PASS readiness=GAPS_CONFIRMED surfaces=8 high_risk_gaps=5
focused tests: 4 passed; target statement/branch coverage: 100%
aggregate regression: 6298 passed, 1 known warning
statement=75838/76719=98.85165343656722%
branch=17664/18314=96.45080266462816%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
