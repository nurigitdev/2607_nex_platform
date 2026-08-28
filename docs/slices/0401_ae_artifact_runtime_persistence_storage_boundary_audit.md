# Slice 0401: AE Artifact Runtime Persistence/Storage Boundary Audit

## Scope

Freeze the current AE artifact runtime boundary before adding durable
PostgreSQL persistence and rendered artifact storage.

## Findings

- AE API is the artifact system of record for handoffs, artifact records,
  render jobs, artifact files, and preview/download links.
- CX remains the source generation and structured draft system of record.
- The current AE artifact route surface already supports artifact creation,
  synchronous Markdown render jobs, artifact file metadata, bounded preview, and
  download payload routes.
- Runtime persistence is still process-local through `ArtifactHandoffStore` and
  `ArtifactRecordStore`.
- Rendered Markdown payloads are still stored in process memory via
  `rendered_markdown`.
- Public artifact metadata uses logical `ae://` storage refs and AE
  preview/download routes, not local filesystem paths.

## Decisions

- Durable artifact metadata should move into the `nex_ae` database, not CX.
- Rendered artifact payloads should move behind an AE-owned storage adapter:
  local `NEX_AE_ARTIFACT_STORAGE_ROOT` first, object storage later.
- Preview/download APIs should keep the same owner-checked AE route boundary
  while changing only the private backing store.
- Standard regression can remain SQLite/mock-first; PostgreSQL evidence should
  be a protected test-profile smoke.

## Next Slices

- Slice 0402: AE artifact PostgreSQL schema migration foundation.
- Slice 0403: AE artifact SQLAlchemy repository + SQLite regression.
- Slice 0404: AE rendered artifact local storage adapter.
- Slice 0405: AE artifact service API persisted wiring.
- Slice 0406: AE artifact PostgreSQL smoke evidence.

## Evidence

- `./.venv/bin/python scripts/smoke/run_ae_artifact_runtime_persistence_storage_boundary_audit.py --summary`
  - `ae_artifact_runtime_persistence_storage_boundary_audit=pass paths=16/16 token_groups=8/8 gaps_ready=0/6 next=Slice_0402`
- `./.venv/bin/pytest tests/test_ae_artifact_runtime_persistence_storage_boundary_audit.py -q --cov=run_ae_artifact_runtime_persistence_storage_boundary_audit --cov-branch --cov-report=term-missing`
  - `5 passed`; audit runner statement/branch coverage `100%`.
- `scripts/quality/run_quality_gate.sh`
  - `2895 passed, 1 warning`
  - `statement_coverage=98.70% threshold=95.00%`
  - `branch_coverage=96.16% threshold=85.00%`
  - `contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7`
