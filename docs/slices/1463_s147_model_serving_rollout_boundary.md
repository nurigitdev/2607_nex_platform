# Slice 1463: S147 Model-Serving Capacity and Rollout Boundary

## Outcome

- Froze a model-independent production admission boundary for embedding,
  reranking, and generation revisions.
- Defined immutable revision/deployment identity, product-neutral GPU capacity
  scheduling, exact-revision readiness, capability-specific calibration,
  bounded canary, atomic alias activation, and exact rollback invariants.
- Registered eight implementation gaps and the Slice 1464-1472 sequence.
- Limited protected acceptance to non-disruptive DGX/provider observation and
  `nex_mo_test` rehearsal; no live provider process or production alias may be
  mutated by the smoke path.

## Decision

The current single DGX host is one capacity pool behind a scheduler-neutral
contract. Model names remain catalog metadata. Promotion decisions use stable
capability, catalog, revision, deployment, artifact, request-shape, calibration,
and runtime evidence.

Production deployment remains unapproved. Slice 1464 adds the immutable
revision and capacity snapshot domains.

## Verification

- Focused boundary regression: `4 passed`, statement `100.00%`, branch
  `100.00%`.
- MO Slice Gate: `1,097 passed`, `6 skipped`, statement `99.84%`, branch
  `99.24%`.
- Contract validation: `166` schemas, `228` examples, `196` negative cases,
  and `7` OpenAPI documents.
- Boundary audit: `11/11` checks, three capabilities, eight gaps, ten Slices,
  `next=1464`.
