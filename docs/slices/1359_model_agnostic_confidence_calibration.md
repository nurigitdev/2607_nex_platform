# Slice 1359: Model-Agnostic Confidence Calibration

## Goal

Prevent embedding, reranker, or generation model changes from silently
reusing an unrelated confidence threshold. Admit a threshold only after an
evidence-backed evaluation for the exact model and retrieval policy binding.

## Implementation

- Added a shared binary score-calibration evaluator with minimum sample,
  false-READY, and READY-recall constraints.
- Bound each profile to capability, model revision, request shape, score
  semantics, and policy ID; only one exact ACTIVE profile may be selected.
- Added CANDIDATE, ACTIVE, and RETIRED lifecycle states and a hash-bound JSON
  profile contract.
- Made unknown, changed, missing, or ambiguous model profiles fail closed as
  CALIBRATION_REQUIRED instead of inheriting a default threshold.
- Added a public bilingual 36-sample reranker dataset and a protected live
  runner that persists neither request text nor individual sample scores.
- Kept the Slice 1357 `0.2` value as a deterministic regression baseline only;
  this Slice does not activate it for a live model.

No database table, migration, production threshold, or retrieval route was
changed.

## Live Evidence

The protected run used `Qwen3-Reranker-4B` with 12 positive and 24 negative
document judgments. The evaluator requires at least 20 total samples, 8 per
class, false-READY rate at most `0.10`, and READY recall at least `0.80`.

The live score distributions overlapped:

- positive: min `0.825474`, max `0.945073`, mean `0.89648108`
- negative: min `0.74155`, max `0.938141`, mean `0.85330512`
- overlap: `0.112667`

No threshold satisfied both constraints. The best-effort threshold `0.886183`
still produced false-READY rate `0.29166667` and READY recall `0.66666667`.
The activation gate therefore returned `NO_ACCEPTABLE_THRESHOLD`, emitted no
CANDIDATE profile, and left the runtime threshold unchanged.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_model_calibration.py \
  --test tests/test_s136_model_calibration_live.py \
  --coverage-target services/_shared/nex_runtime/model_calibration.py \
  --coverage-target scripts/smoke/run_s136_model_calibration_live.py \
  --smoke scripts/smoke/run_s136_model_calibration_live.py
```

Protected diagnostic invocation:

```bash
NEX_S136_MODEL_CALIBRATION_LIVE=1 \
NEX_MO_REMOTE_RERANKER_URL=http://192.168.20.243:9113/v1/rerank \
NEX_MO_REMOTE_RERANKER_API_KEY='<redacted>' \
NEX_MO_REMOTE_RERANKER_MODEL=Qwen3-Reranker-4B \
./.venv/bin/python scripts/smoke/run_s136_model_calibration_live.py \
  --output /tmp/s136-calibration-evidence.json
```

The protected diagnostic is expected to exit nonzero until an evaluation can
produce a safe CANDIDATE profile. This is an activation-gate rejection, not a
provider connectivity failure.

Observed Slice Gate: `2383 passed`; statement coverage `99.10%`, branch
coverage `98.22%`, and both changed runtime targets reached `100%` statement
and branch coverage. Contract validation passed
with 160 schemas, 218 examples, 187 negative examples, and 7 OpenAPI documents.

## Decision Required Before Slice 1360

The current model evidence shows that one native reranker score is not a
sufficient confidence signal for this dataset. Slice 1360 must not relax the
constraints or select an arbitrary threshold. It requires an explicit decision
on a model-agnostic multi-signal calibration strategy before live retrieval can
classify READY.
