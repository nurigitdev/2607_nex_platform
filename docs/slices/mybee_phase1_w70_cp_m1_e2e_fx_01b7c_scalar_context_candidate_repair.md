# CP-M1-E2E-FX-01B.7C: Scalar Context Candidate Repair and Provider Contract Hardening

## Purpose

The DGX-backed installed M1 journey reached CONTEXT candidate generation, but
Qwen3.5-9B returned an object or array in `parameter_candidates[].value`. The
canonical candidate contract intentionally admits scalar JSON values only, so
the response was rejected as `CANDIDATE_SCHEMA_INVALID` with diagnostic
`CONTEXT_PARAMETER_VALUE_TYPE_IS_INVALID` before WC claim handoff.

This corrective Slice preserves the scalar contract and adds one narrow,
observable regeneration path for that exact provider formatting defect.

## Decision

- Keep `p65.context_candidate_set.v1` scalar-only. Do not widen the schema to
  accept objects or arrays.
- Attempt repair only for the exact error and diagnostic pair above.
- Permit one repair attempt and never recurse or retry the repair response.
- Use a dedicated Prompt Registry binding and a distinct deterministic request
  ID so MO idempotency cannot replay the rejected first response.
- Send only the original trusted generation input and the bounded diagnostic to
  the repair call. Never include the malformed provider output.
- Keep the readiness-selected model profile, model reference, deployment, and
  route unchanged.
- Rerun model-lineage and full candidate validation after repair. Authority,
  prompt-injection, other schema, second malformed, or provider failures remain
  fail-closed.
- Persist repair outcome evidence through the existing service log store. Do
  not add a database migration or a new API field.

## Implementation

- Added Prompt Registry binding `ae.context_candidate_repair.default` with an
  explicit scalar-output and single-attempt contract.
- `LiveContextCandidateService` now recognizes only the admitted diagnostic,
  constructs a bounded repair input, invokes generation once, and reuses the
  canonical parser and model-lineage guard.
- Repair request IDs are derived from the original request and trace IDs under
  a domain-separated hash.
- Durable evidence records success or rejection, timing, generation IDs,
  output digests, prompt versions, and immutable model/deployment/route
  lineage. It records `invalid_output_included=false` rather than retaining the
  rejected content.
- Installed semantic-candidate composition injects a `ServiceLogEmitter` backed
  by the existing AE service log store. Evidence persistence failure returns
  retryable `CONTEXT_REPAIR_EVIDENCE_UNAVAILABLE` instead of silently accepting
  an unobservable repair.

## Fail-Closed Matrix

| Condition | Result |
| --- | --- |
| Exact scalar-value diagnostic | One bounded repair attempt |
| Second malformed response | Rejected; no further repair |
| Authority, tenant, privacy, or injection violation | Rejected without repair |
| Other schema diagnostic | Rejected without repair |
| Repair provider timeout/failure | Propagated and observed |
| Repair evidence persistence failure | Retryable fail-closed rejection |

## Verification

- Focused semantic and prompt regression: `226 passed`.
- Prompt persistence regression: `101 passed`.
- AE Slice Gate: `6824 passed, 51 skipped`.
- AE statement coverage: `96.40%` with threshold `95.00%`.
- AE branch coverage: `94.64%` with threshold `94.00%`.
- Product coverage: statement `97.02%`, branch `94.94%`.
- Contract validation: schemas `274`, examples `320`, negatives `260`,
  OpenAPI documents `10`; all passed.
- Golden Journey transition audit, Demo product dependency audit, AE coverage
  ownership, and all six tiered gates: `PASS`.
- Actual `nex_ae_test` PostgreSQL smoke inserted and selected one durable repair
  evidence record, then deleted it; cleanup residue was zero.
- No database migration, public API schema widening, or provider-specific
  business fallback was added.

## Protected Live Rule

The actual installed journey must be rerun against the canonical Qwen3.5-9B
provider before `CP-M1-E2E-FX-01B.7` can close. The run must prove:

1. scalar-invalid CONTEXT output is either absent or repaired at most once;
2. repair evidence contains no rejected provider content;
3. execution reaches authoritative WC claim and AE handoff;
4. synchronous planning completes within the 600-second claim lease;
5. replay, failure, and cleanup remain fail-closed with zero isolated residue.

Until that protected run passes, this Slice closes the source, regression, and
actual PostgreSQL evidence boundary only.
