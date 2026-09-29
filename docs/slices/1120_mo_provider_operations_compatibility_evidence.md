# Slice 1120: MO provider operations compatibility evidence

## Goal

Prove that the S112 runtime decomposition preserves protected provider
operations, canonical model identity, and BF16 process safety without placing
protected runtime values in repository evidence.

## Result

- One opt-in runner composes the architecture guard, canonical DGX profile
  preflight, three live provider requests, and the remote process dtype probe.
- Default regression remains deterministic and network-free; protected live
  execution is required only when
  `NEX_MO_PROVIDER_OPERATIONS_COMPATIBILITY_LIVE=1` is set.
- Live activation fails closed unless all three protected components pass.
- The committed evidence shape excludes endpoints, API keys, SSH targets,
  process command lines, model paths, and provider request/response payloads.
- No PostgreSQL table or migration is introduced. Durable operational metrics
  remain assigned to S116 and GPU resource monitoring remains assigned to S117.

## Observed Protected Evidence

- Canonical profile configuration and provider preflight: PASS.
- Live embedding, reranking, and generation requests: 3/3 PASS.
- Expected provider processes with confirmed BF16: 3/3 PASS.
- Explicit BF16 process launch configuration: 3/3 PASS.
- Evidence redaction: PASS.

Slice Gate passed with 303 tests, statement coverage 99.59%, and branch
coverage 98.46%. The new compatibility runner has 100% statement and branch
coverage. Contract validation passed with 109 schemas, 167 examples, 132
negative examples, and 7 OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_operations_compatibility.py \
  --cov=run_mo_provider_operations_compatibility \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_operations_compatibility.py --summary

NEX_MO_PROVIDER_OPERATIONS_COMPATIBILITY_LIVE=1 \
./.venv/bin/python \
  scripts/smoke/run_mo_provider_operations_compatibility.py --summary
```

Protected live evidence is written only to the terminal or `/tmp`; credentials
and endpoint values are not committed.
