# P8-S52: NSL ApprovalResumeCoordinator Integration

## Status

Completed on 2026-10-22.

## Scope

- Added an asynchronous Platform integration over the admitted NSL v0.2
  `ResumeToken` and `ApprovalResumeCoordinator` public types.
- Resolves the exact running resume authority from P8-S51.
- Loads the protected canonical ApprovalRequest from the P8-S44A PostgreSQL
  boundary and immutable Platform ApprovalEvidence from P8-S48.
- Projects evidence through the P8-S49 admitted NSL type and invokes the NSL
  coordinator without importing a private NSL module.

## Identity And Authority

The integration creates no new execution or approval identity:

- `ResumeToken.execution_id` is the persisted `nsl_execution_id`;
- `ResumeToken.business_operation_id` is the persisted BusinessOperationId;
- `ResumeToken.checkpoint_version` is the exact persisted wait version;
- the existing deterministic RuntimeJobId is reused as the NSL checkpoint
  `claim_id`;
- ApprovalId, write node, current write-intent hash, and payload hash come from
  the protected canonical ApprovalRequest rather than caller input.

Before coordinator invocation, tenant, agent execution, executable step,
approval request/work item, NSL execution, business operation, evidence
integrity, and request/evidence semantic bindings must all agree. Drift fails
closed.

## Persistence And Provider Boundary

No migration or new table was added. The Slice composes the existing P8-S44A,
P8-S48, and P8-S51 sources of record. Remote model providers are not involved.

The admitted NSL v0.2 package is isolated from the host v0.1 runtime. P8-S52
proves the Platform assembly and invocation boundary with public-type faithful
tests. The actual admitted wheel, persisted checkpoint, and PostgreSQL journey
are exercised together by the P8-S53 protected gate.

## Verification

- P8-S52 focused tests: `16 passed`.
- P8-S52 module coverage: statement `100%`, branch `100%`.
- P8-S49 through P8-S52 focused regression: `80 passed`.
- AE Slice Gate: `4,794 passed`, `23 skipped`.
- AE Slice Gate coverage: statement `98.36%`, branch `96.27%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- Ruff and diff checks passed.

## Exit Decision

P8-S52 is closed. P8-S53 may now execute the actual PostgreSQL approval resume
journey and the admitted NSL v0.2 coordinator, including mismatch, expiry, and
reject scenarios, while stopping before any EOS business mutation.
