# Slice 0059 Protected Live Smoke Evidence Writer

Status: Implemented.

Backlog candidate: `S6-009` Protected live smoke evidence writer.

Requirement coverage: `MO-FR-004`, `PLAT-FR-006`, `PLAT-FR-007`,
`TRACE-MO-001`.

## Scope

Slice 0059 strengthens the manual DGX live provider preflight evidence path:

- `scripts/smoke/run_dgx_live_provider_preflight.py` keeps the existing
  deterministic preflight runner and summary behavior.
- `--output` remains supported and `--evidence-output` is added as an alias for
  protected JSON evidence output.
- JSON output includes `dgx_live_provider_preflight_evidence.v1` metadata,
  generation time, and redaction policy status.
- The writer checks configured endpoint/API-key environment values before
  writing evidence and fails if any such value appears in the serialized output.
- The guard covers current and legacy live provider endpoint env names.
- Evidence remains safe by construction: preflight checks record env key names,
  method, request shape, expected model names, authorization presence, and
  structural validation facts, not raw endpoint URLs, API keys, or response
  bodies.

The recommended output location is under `reports/`, which is already ignored
by git. Live evidence can be copied into a release package only after review.

## Files

- `scripts/smoke/run_dgx_live_provider_preflight.py`
- `services/nex-mo/README.md`
- `tests/test_dgx_live_provider_preflight.py`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_dgx_live_provider_preflight.py
scripts/quality/run_quality_gate.sh
./.venv/bin/python scripts/smoke/run_dgx_live_provider_preflight.py --summary
```

The default live smoke command remains skipped unless `NEX_MO_LIVE_PREFLIGHT=1`
is explicitly set.
