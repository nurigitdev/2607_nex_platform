# Slice 1308: Platform AE artifact-to-AG audit path audit

## Outcome

- Confirmed AE generated-response lineage binds the interaction, CX generation,
  and content hash and is attached to artifact handoff records. Trace remains
  on the surrounding chat, artifact, and CX generation records.
- Confirmed AG has HTTP clients for CX generation/event reads, AE artifact and
  recovery reads, and the wider AE artifact operations surface.
- Confirmed AG clients propagate service identity, request ID, and trace
  context, and generation audit projections apply an explicit raw-field
  denylist.
- Identified a P0 live integration mismatch: CX generation reads require tenant
  and subject context, while `HttpGenerationAuditSourceClient` sends neither.
  Its unit tests mock the remote HTTP response and therefore do not prove the
  real CX authorization path.
- Retained the four AG cross-service database adapters only as audited legacy
  compatibility. They are not an acceptable workaround for the owner mismatch.

## Decision

AE remains the artifact and response-lineage owner; AG owns only redacted
operator projections. AG should neither guess a user's owner scope nor read the
CX database. The recommended S138 boundary is an ADMIN-scoped, redacted CX
generation audit projection API that AG can call with its own service identity.
S132 should also unify the two existing AG-to-AE endpoint/token configurations.

No database or remote provider is required for this repository audit Slice.

## Verification

- Focused tests: `4 passed`.
- Slice Gate (`nex-ag`): `2,459 passed`.
- Coverage: statement `98.90%`, branch `96.52%`.
- Changed audit runner coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- Audit summary: `4` AG generation-source operations exist, CX owner context
  is required, AG sends no owner context, and no dedicated CX admin audit
  projection exists.
