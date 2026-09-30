# Slice 1170: MO runtime observability DGX live evidence

## Goal

Prove the S117 runtime collector against the actual DGX GPU and vLLM process
state while keeping SSH identity, process details, model paths, and credentials
outside committed evidence.

## Result

- Added an explicit opt-in protected smoke boundary for the live SSH collector.
- Required one expected process, matching model identity and precision, GPU
  association, complete memory/utilization/temperature metrics, and healthy
  policy classification for embedding, reranking, and generation.
- Failed closed on malformed configuration, collector errors, incomplete
  observations, precision mismatch, resource pressure, and private-value leaks.
- Added a DGX Spark unified-memory fallback: discrete GPU capacity still comes
  from `nvidia-smi`, while `[N/A]` capacity uses `/proc/meminfo` and retains
  per-process allocation from NVIDIA compute-app evidence.
- Restricted optional detailed evidence files to `/tmp`; only redacted aggregate
  results are recorded in repository documentation.
- Kept the deterministic test path injectable and free of DGX dependencies.
- PostgreSQL remains outside this Slice because runtime samples are deliberately
  ephemeral and S117 introduces no table.

## Live evidence

Protected DGX execution passed on 2026-09-30:

| Check | Result |
| --- | --- |
| Expected runtime models | `3/3` |
| One process per capability | `3/3` |
| BF16 precision match | `3/3` |
| GPU association and complete metrics | `3/3` |
| Aggregate runtime policy | `HEALTHY` |
| Private-value redaction | `PASS` |

The observed unified memory capacity was `124,616 MiB`, temperature was
`63 C`, and compute utilization was `96%`. High compute utilization alone is
intentionally healthy; memory and temperature remained below their configured
warning thresholds. Detailed redacted JSON remains in `/tmp` only.

Slice Gate passed with `742` tests and `2` protected PostgreSQL skips.
Statement coverage was `99.81%`, branch coverage was `99.27%`, and both the
changed collector and protected smoke scopes reached statement/branch `100%`.
Contract validation passed `120` schemas, `178` positive examples, `146`
negative examples, and `7` OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_runtime_observability_live_smoke.py

NEX_MO_RUNTIME_OBSERVABILITY_LIVE_SMOKE=1 \
NEX_MO_DGX_SSH_TARGET='<configured-target>' \
./.venv/bin/python \
  scripts/smoke/run_mo_runtime_observability_live_smoke.py \
  --output /tmp/nex-mo-runtime-observability-live.json \
  --summary
```
