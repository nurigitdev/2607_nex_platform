# P8-S49: NSL ApprovalEvidence Projection / Verifier

## Status

Completed on 2026-10-22.

## Scope

- Added an AE-owned projection from immutable Platform ApprovalEvidence to the
  admitted NSL v0.2 public `ApprovalEvidence` type.
- Kept the host NSL v0.1 installation unchanged. The projection receives the
  v0.2 public type from the admitted `NslV02PublicApiAdapter` boundary instead
  of importing private NSL modules.
- Preserved the frozen mappings `nsl_execution_id -> execution_id`, `APPROVE ->
  APPROVED`, and `REJECT -> REJECTED`.
- Added a structural `ApprovalEvidenceVerifier` implementation that resolves
  the canonical AE evidence by tenant and request identity, verifies the exact
  projected bindings, proves the current WC terminal work-item/decision, and
  rechecks current OA `approval:decide` authority.
- Kept the Platform provenance verifier separate from NSL deterministic
  semantic validation.

## Failure Semantics

Verification returns `False` for missing or tampered AE evidence, cross-tenant
or changed WC lineage, non-terminal or different decisions, inactive or
insufficient OA authority, revision/decision-reference drift, malformed source
responses, and source unavailability. No cached ALLOW or Platform field can
override the original NSL request bindings.

## Persistence

No migration was added. `ae_approval_evidence` remains the canonical immutable
Platform evidence store. WC and OA are represented by source protocols; the AE
bridge does not read another service's database directly.

## Verification

- Focused projection/verifier tests: `16 passed`.
- Focused module coverage: statement `100%`, branch `100%`.
- AE Slice Gate: `4,730 passed`, `22 skipped`.
- AE Slice Gate coverage: statement `98.34%`, branch `96.24%`.
- New module gate scope: statement `100%`, branch `100%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- Ruff and diff checks passed.

## Exit Decision

P8-S49 is closed. AE can project canonical approval provenance through the NSL
v0.2 public type and provide a fail-closed authority verifier. Typed approval
event intake remains P8-S50 scope.
