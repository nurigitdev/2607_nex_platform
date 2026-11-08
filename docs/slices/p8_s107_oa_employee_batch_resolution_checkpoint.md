# P8-S107: OA Employee Batch Resolution and Checkpoint

## Scope

P8-S107 adds the protected OA authority boundary used to resolve a bounded
batch of employee candidates before NVTProject membership admission.

- `POST /internal/v1/identity/employees:resolve-batch` accepts at most 50
  independent candidates.
- Employee IDs resolve through the existing credential registry, subject
  state through the existing subject registry, and tenant eligibility through
  the existing membership registry.
- The route requires a signed service bearer with both `service:call` and
  `identity:employee:resolve` scopes and is classified as READ.
- No database table or migration is added.

## Resolution Semantics

Each candidate receives exactly one terminal status:

- `RESOLVED`
- `INVALID_EMPLOYEE_ID`
- `EMPLOYEE_NOT_FOUND`
- `SUBJECT_INACTIVE`
- `NAME_MISMATCH`
- `DUPLICATE_INPUT`

Employee IDs are canonicalized before duplicate detection. Display names are
compared after NFC normalization, trim, internal whitespace collapse, and
case folding. The first occurrence of a canonical employee ID is evaluated;
later occurrences are reported as duplicates without changing the first
result.

Cross-tenant and absent employees deliberately share the public
`EMPLOYEE_NOT_FOUND` result. Only `RESOLVED` items expose the subject ID,
canonical display name, and subject/membership revisions. Rejected items do
not leak authority identifiers. Registry, persistence, or malformed authority
failures are operation-level retryable `503` responses rather than candidate
business outcomes.

The response includes a deterministic, domain-separated
`resolution_evidence_hash` over the tenant, ordered candidate outcomes, and
authority revisions. This evidence can be bound by P8-S108 without treating
the OA response as mutable planning input.

## Contract Surface

- canonical request and response JSON Schemas
- mixed positive request/response examples
- negative fixtures for private-field requests and rejected-subject leakage
- OpenAPI operation and canonical-schema links
- updated OA contract-drift evidence inventory

Contract validation passed with `201` schemas, `265` positive examples, `227`
negative examples, and `9` OpenAPI documents.

## Verification

- focused OA unit, route, contract, and regression tests: `17 passed`
- related OA contract and evidence regression: `46 passed`
- Checkpoint Gate: `PASS` (`4/4` commands, `753.512` seconds)
- repository statement coverage: `98.66%`
- repository branch coverage: `97.15%`
- employee batch resolver statement coverage: `99.28%`
- employee batch resolver branch coverage: `97.37%`
- Ruff, contract validation, and `git diff --check`: passed

The Checkpoint Gate report is
`reports/quality/p8-s107-checkpoint.coverage.json`; the tier summary is
`reports/quality/checkpoint-latest.json`.

## Exit

P8-S107 is complete. P8-S108 may consume only `RESOLVED` candidates, preserve
the OA evidence hash and authority revisions, and reject an empty admitted
membership set before approval or controlled WRITE execution.
