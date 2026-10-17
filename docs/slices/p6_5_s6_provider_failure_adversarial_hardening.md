# P6.5-S6 Provider Failure / Adversarial Hardening

**Status:** IMPLEMENTED
**Date:** 2026-10-17
**Predecessor:** P6.5-S5 Deterministic Candidate Admission / Compile Integration

## Scope

P6.5-S6 proves that provider, candidate, persistence, and adversarial failures
cannot bypass the deterministic planning boundary:

```text
MO final provider failure or untrusted candidate
-> closed AE failure taxonomy
-> sanitized stage/directive projection
-> no PlanValidation
-> no ExecutablePlan
-> no RuntimeJob
```

The Slice does not add a database table, change candidate evidence identity,
create an AE-side provider retry loop, or execute runtime work. MO continues to
own bounded technical retry. AE continues to own semantic retry/replan after a
final provider or candidate outcome.

## Failure Policy

`semantic_candidate_failures.py` is the common fail-closed projection boundary.
It accepts only known exception types and an allowlisted taxonomy.

Provider failures:

```text
PROVIDER_NOT_READY
PROVIDER_TIMEOUT
PROVIDER_RATE_LIMIT
PROVIDER_SERVER_ERROR
PROVIDER_RESPONSE_INVALID
```

Candidate failures:

```text
CANDIDATE_JSON_INVALID
CANDIDATE_SCHEMA_INVALID
CANDIDATE_AUTHORITY_VIOLATION
CANDIDATE_PRIVATE_DATA_VIOLATION
CANDIDATE_CAPABILITY_UNKNOWN
CANDIDATE_DEPENDENCY_INVALID
CANDIDATE_BOUNDS_EXCEEDED
CANDIDATE_PLAN_INVALID
CANDIDATE_LOW_CONFIDENCE
PROMPT_INJECTION_OR_POLICY_BLOCK
SEMANTIC_CALIBRATION_REQUIRED
```

Retryable provider failures produce `RETRY_PROVIDER`; malformed semantic
suggestions produce `REPLAN_REQUIRED`; authority, private-data, and injection
violations produce `BLOCKED`. Defensive low-confidence exception projection is
stage-specific, while the normal admitted low-confidence path remains the S2-S5
result flow with clarification, context refresh, or replan.

The projection normalizes status codes at the AE boundary. In particular, an
upstream provider authentication/readiness failure is exposed as service
readiness failure rather than caller authentication failure. `Retry-After` is
retained only for a rate-limit result and only within the existing 0-300 second
bound.

## Deterministic Authority

`DeterministicCandidateAdmissionService` now wraps known failures at the exact
INTENT, CONTEXT, or PLAN stage. The wrapper records only safe category,
taxonomy, stage, directive, retryability, and bounded retry timing. It does not
persist a fabricated failed candidate or allocate a semantic revision when no
candidate was admitted.

The S6 integration matrix verifies failures at all three stages. A failed stage
may leave immutable, already-admitted predecessor stages for restart, but it
cannot create the failed stage payload, AgentPlan validation, ExecutablePlan,
RuntimeJob, or executor work. Repeating the same admitted interaction after a
final CONTEXT timeout resumes INTENT evidence, preserves AgentExecution and
candidate identities, and invokes only CONTEXT and PLAN.

## Adversarial Boundary

S6 composes the existing S1-S5 parser and binder guards with the complete
admission pipeline. The covered matrix includes:

```text
endpoint unavailable, timeout, exhausted 429/Retry-After, 5xx
invalid upstream JSON and model/readiness failure
non-JSON candidate and forbidden extra fields
invented tenant, principal, role, project, approval, or delegation authority
provider-private or hidden-reasoning fields
user/candidate/retrieved-data prompt-control language
unknown capability and model-authored Skill/version authority
invalid dependency, cycle, serial-width, and plan bounds
low confidence and in-flight Prompt Registry pointer change
```

Detailed parser cases remain in the S2, S3, and S4 regressions. S6 adds the
cross-pipeline assertion that these rejected inputs never reach deterministic
validation or compilation.

## Privacy And Chat Boundary

The Chat boundary no longer trusts arbitrary exception attributes. Only the
typed `SemanticCandidateAdmissionError` can carry the safe taxonomy outward;
unknown or forged exceptions become `SEMANTIC_ADMISSION_FAILED` with
`BLOCKED` and a static detail.

Problem details and failed-chat evidence may contain only:

```text
semantic stage
safe directive
bounded retry-after seconds
retryable flag
allowlisted error code
```

Provider endpoint, upstream error detail, API key, model path, raw prompt, raw
provider response, candidate payload, and hidden reasoning are excluded. Failed
chat evidence explicitly retains `raw_error_detail_included=false`.

## Verification

```text
S6 dedicated tests: 40 collected
S6 plus adjacent S5 admission/route regression: 55 passed
P6.5 S1-S6 contract/adversarial regression: 381 passed
Focused P6.5 statement coverage: 98.74%
Focused P6.5 branch coverage: 97.28%
semantic_candidate_failures statement/branch coverage: 100.00% / 100.00%
semantic_candidate_admission coverage: 99%
AE Slice Gate: PASS, 4,350 passed, 10 protected-smoke skips
AE Slice Gate statement coverage: 98.62%
AE Slice Gate branch coverage: 96.85% (previous 96.82%)
Contract validation: PASS, 174 schemas, 236 examples,
204 negative examples, 7 OpenAPI documents
```

The ten skips are existing opt-in PostgreSQL/live tests. S6 intentionally uses
deterministic failure injection and mock provider boundaries: deliberately
breaking the shared live provider is neither needed nor desirable for this
matrix. The frozen sequence assigns actual `nex_ae_test` PostgreSQL plus live
Remote Generation Provider integration, zero-residue verification, and final
Full Gate to P6.5-S7.

## Exit

P6.5-S6 is closed when every known provider and candidate failure maps to a
bounded safe directive, unknown failures cannot leak private attributes, retry
or restart preserves admitted identity, and no negative path creates executable
work without candidate schema, authority validation, PlanValidation `VALID`,
and deterministic compiler success. P6.5-S7 may now run the actual PostgreSQL
and live-provider Golden Journey.
