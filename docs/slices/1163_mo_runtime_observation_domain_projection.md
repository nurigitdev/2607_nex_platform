# Slice 1163: MO runtime observation domain and projection

## Goal

Define validated GPU/model runtime observations and a privacy-safe public
snapshot before any live collector is introduced.

## Result

- Added immutable per-capability model runtime observations for embedding,
  reranking, and generation.
- Kept requested and loaded dtype separate and normalized common BF16/FP16/
  FP32/NVFP4 aliases without inferring an unknown value.
- Validated process/GPU counts, memory, utilization, temperature, status,
  source, model identity, and timezone-aware observation timestamps.
- Added aggregate snapshot semantics that fail closed to `UNKNOWN` for stale,
  incomplete, or unknown evidence.
- Added a deterministic mock snapshot with no network, process, or database
  dependency and a public projection that omits all protected runtime details.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_runtime_observability_domain.py
./.venv/bin/python \
  scripts/smoke/run_mo_runtime_observability_domain.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_runtime_observability_domain.py \
  --coverage-target services/nex-mo/nex_mo/runtime_observability.py \
  --coverage-target \
  services/nex-mo/nex_mo/runtime_observability_projection.py \
  --smoke scripts/smoke/run_mo_runtime_observability_domain.py
```

## Quality Evidence

- Focused domain and legacy architecture regression: `52 passed`.
- Slice Gate: `651 passed`, `2` protected PostgreSQL skips.
- Coverage: statement `99.78%`, branch `99.15%`; both changed runtime domain
  and projection scopes `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Deterministic evidence projected `3/3` healthy models with `3/3` precision
  matches and zero protected fields.
