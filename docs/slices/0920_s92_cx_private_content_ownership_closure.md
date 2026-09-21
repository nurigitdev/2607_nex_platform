# Slice 0920: S92 CX Private Content and Ownership Closure

## Closure result

S92 closes as `READY_FOR_S93` with
`CX_PRIVATE_CONTENT_AND_OWNERSHIP_HARDENED` readiness.

- All eight deterministic S92 evidence builders pass.
- Authenticated `CxAccessContext` is resolved once and propagated with the
  canonical tenant and subject headers.
- Eleven private CX route modules enforce the centralized owner guard, while
  cross-owner resources remain indistinguishable from missing resources.
- Private text and vector payloads use restart-safe, owner-scoped capability
  adapters. Public PostgreSQL stores only metadata, hashes, URIs, dimensions,
  and canonical owner lineage.
- Jobs, processing runs, retrieval packages, generation executions, and
  remediation attempts carry owner lineage. Mixed-owner retrieval packages and
  prompt-bearing generation metadata are rejected.
- OpenAPI and all CX negative-fixture families have zero known drift.

## Actual PostgreSQL evidence

The protected Slice 0919 runner connected to the actual
`nex_cx_user@nex_cx_test` database, applied the Slice 0917 migration, committed
and re-read 16 evidence rows for two owner scopes, passed all 17 checks, and
verified zero-residue cleanup. SQLite was not substituted for this proof.

## Decisions

- The versioned SQL plus `schema_migrations` runner remains the single migration
  history.
- The current private text/vector filesystem adapters stay replaceable by
  object storage and a vector database without changing domain callers.
- Production object storage, production vector-database integration, and
  provider-backed content-quality validation remain deferred.
- DGX Spark is not required for S92 because this requirement hardens storage,
  authorization, and persistence without invoking model providers.
- The next requirement is identified only as S93; its title and slice scope are
  intentionally left for the next review.

## Verification

```bash
./.venv/bin/pytest -q tests/test_s92_cx_private_content_ownership_closure.py
./.venv/bin/python \
  scripts/smoke/run_s92_cx_private_content_ownership_closure.py --summary
```

The final quality gate passed 6,540 tests. Statement coverage was
98.8316685353175% and branch coverage was 96.39944194033055%. Contract
validation remained at 82 schemas, 133 examples, 98 negative examples, and 7
OpenAPI specifications. The protected PostgreSQL evidence independently passed
all 17 checks against the actual `nex_cx_test` database.

The closure adds no table, index, or migration.
