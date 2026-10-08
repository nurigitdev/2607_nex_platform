# Slice 1464: S147 Model Revision and Capacity Domain

## Outcome

- Added immutable, model-independent identity for embedding, reranking, and
  generation candidates.
- Bound catalog, revision, deployment, artifact, runtime engine, precision,
  and request-shape identity into one deterministic fingerprint.
- Added product-neutral GPU node and capacity snapshots with allocatable GPU,
  memory, concurrency, queue, pressure, health, and freshness fields.
- Kept model names, endpoints, credentials, and provider payloads outside the
  policy domain and evidence projection.

Slice 1465 consumes this domain to implement deterministic placement,
reservation, and capacity admission.

## Verification

- Focused regression: `27 passed`; new domain and smoke statement/branch
  coverage `100.00%`.
- MO Slice Gate: `1,120 passed`, `6 skipped`, statement `99.84%`, branch
  `99.26%`.
- Contract validation remained `166/228/196/7`; domain smoke passed `9/9`
  checks with three unique capability identities.
