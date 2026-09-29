# Slice 1110: MO protected DGX live re-audit

## Goal

Collect protected runtime evidence for the selected MO providers and prove that
the DGX vLLM processes do not repeat the earlier implicit FP32 loading risk.

## Result

- The canonical `dgx_vllm` profile passed local configuration validation and
  live provider preflight for embedding, reranking, and generation.
- Protected live requests passed for all three capabilities. Embedding returned
  2,560 dimensions, reranking returned ranked results, and generation finished
  with `STOP`.
- The first generation smoke attempt exhausted its 32-token budget in provider
  thinking and returned no answer content. The deterministic smoke request now
  sets `reasoning_mode=disabled`; production request policy is unchanged.
- A protected SSH process probe confirmed three expected vLLM processes and
  explicit `bfloat16` launch dtype on all three provider ports.
- The probe emits only capability, port, normalized dtype/task, expected-model
  match, and assertion results. SSH target, PID, command line, model path, API
  key, endpoint, prompts, and generated text are excluded.
- Evidence JSON was written only below `/tmp`; no protected runtime evidence or
  credential is committed.
- PostgreSQL is outside this Slice because MO still has no durable schema or
  database-owned runtime record.

## Observed Evidence

| Check | Result |
| --- | --- |
| Canonical profile configuration | PASS |
| Provider preflight | 3/3 PASS |
| Protected provider requests | 3/3 PASS |
| Expected model identity | 3/3 PASS |
| Explicit BF16 process dtype | 3/3 PASS |
| Evidence redaction | PASS |

Slice Gate passed with 260 tests, statement coverage 99.73%, branch coverage
98.67%, and 100% statement/branch coverage for both changed smoke scripts.
Contract validation passed with 109 schemas, 167 examples, 132 negative
examples, and 7 OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_dgx_process_dtype_probe.py \
  tests/test_protected_remote_provider_live_smoke.py \
  --cov=run_mo_dgx_process_dtype_probe \
  --cov=run_protected_remote_provider_live_smoke \
  --cov-branch --cov-report=term-missing

NEX_MO_DGX_PROCESS_DTYPE_PROBE=1 \
NEX_MO_DGX_SSH_TARGET='<configured-target>' \
./.venv/bin/python \
  scripts/smoke/run_mo_dgx_process_dtype_probe.py --summary

NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE=1 \
NEX_MO_PROTECTED_LIVE_PROFILE=dgx_vllm \
./.venv/bin/python \
  scripts/smoke/run_protected_remote_provider_live_smoke.py --summary
```
