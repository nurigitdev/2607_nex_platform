# Slice 1152: MO provider telemetry persistence boundary

## Goal

Freeze the S116 persistence, concurrency, privacy, compatibility, and delivery
boundaries before replacing process-local provider telemetry.

## Result

- S116 owns restart-safe aggregate telemetry for embedding, reranking, and
  generation provider executions. It does not persist raw request events.
- The reserved table name is `mo_provider_telemetry`, with the logical key
  `(capability, request_shape, deployment_id, model_revision)`.
- Counters use atomic increment upserts across MO processes. A new store
  instance must read the same aggregate after restart.
- Durable counters are merged with current privacy-safe runtime configuration
  during reads, preserving `mo_provider_telemetry_snapshot.v1`.
- Endpoints, credentials, authorization headers, payloads, and exception
  details are forbidden from persistence. GPU metrics remain S117 scope.
- Memory mode remains deterministic and database-free. The protected database
  smoke will use the actual `nex_mo_test` database and clean its evidence rows.

## Planned Slices

1. Slice 1153: durable telemetry domain and persistence contract.
2. Slice 1154: MO migration and SQLAlchemy durable store.
3. Slice 1155: atomic success/failure/retry aggregation adapter.
4. Slice 1156: service runtime wiring and fifth-Slice Checkpoint Gate.
5. Slice 1157: restart recovery and concurrent aggregation hardening.
6. Slice 1158: authenticated durable telemetry API projection.
7. Slice 1159: contract, privacy, and operations hardening.
8. Slice 1160: protected PostgreSQL restart smoke evidence.
9. Slice 1161: S116 closure and Full Gate.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_telemetry_persistence_boundary.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_telemetry_persistence_boundary.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_telemetry_persistence_boundary.py \
  --coverage-target \
  services/nex-mo/nex_mo/provider_telemetry_persistence_boundary.py \
  --smoke scripts/smoke/run_mo_provider_telemetry_persistence_boundary.py
```

## Quality Evidence

- Focused regression: `4 passed`.
- Slice Gate: `532 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.72%`, branch `98.95%`; changed boundary scope
  `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Boundary evidence passed `10/10` checks across six ownership boundaries with
  zero evidence issues.
