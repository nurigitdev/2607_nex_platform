# Slice 1107: MO model precision and resource-safety audit

## Goal

Separate declared model precision from runtime-loaded dtype and GPU resource
evidence, preserving the earlier NeX-PCX lesson that BF16 models can otherwise
be loaded as FP32.

## Result

- The selected embedding, reranking, and generation profiles all declare BF16.
- MO contains no local Transformers model loader or FP32 fallback; model loading
  remains owned by the DGX vLLM provider processes.
- The provider HTTP APIs prove model identity and behavior but do not prove the
  loaded dtype.
- Slice 1110 must inspect protected DGX process or launch-log evidence and
  confirm `--dtype bfloat16`; an FP32 embedding or reranker process is blocking.
- GPU memory and utilization are not projected by MO telemetry. This explicit
  `MO-FR-005` gap is ordered for S112 rather than inferred from HTTP latency.
- Process arguments, host details, and model paths must remain outside public
  API and committed evidence.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_mo_precision_resource_safety_audit.py --summary

./.venv/bin/pytest -q \
  tests/test_mo_precision_resource_safety_audit.py \
  --cov=nex_mo.precision_resource_audit \
  --cov=run_mo_precision_resource_safety_audit \
  --cov-branch --cov-report=term-missing
```
