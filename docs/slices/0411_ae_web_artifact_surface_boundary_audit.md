# Slice 0411: AE Web Artifact Surface Boundary Audit

Status: Implemented.

Freeze the browser-facing artifact boundary before wiring AE Web to the durable
artifact runtime added in S41.

## Scope

Slice 0411 confirms that:

- `nex-ae-web` owns the browser artifact experience.
- `nex-ae-api` remains the artifact system of record.
- The current Web artifact surface is still mock-first and inline-rendered.
- Browser evidence must never expose raw storage paths, service tokens,
  provider endpoints, database URLs, prompts, or source text.
- The next implementation order is client adapter, read model, chat card, then
  preview/download panel.

## Evidence

```bash
./.venv/bin/python scripts/smoke/run_ae_web_artifact_surface_boundary_audit.py --summary
```

Expected summary:

```text
ae_web_artifact_surface_boundary_audit=pass ... next=Slice_0412
```

Regression:

```bash
./.venv/bin/pytest tests/test_ae_web_artifact_surface_boundary_audit.py -q --cov=run_ae_web_artifact_surface_boundary_audit --cov-branch --cov-report=term-missing
```

The audit is local-only and does not open network connections or PostgreSQL
sessions.
