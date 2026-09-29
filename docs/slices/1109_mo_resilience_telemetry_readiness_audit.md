# Slice 1109: MO resilience, telemetry, and readiness audit

## Goal

Separate working MO failure controls from missing provider-operations features
before collecting protected live evidence.

## Result

- Capability-specific timeouts, safe retryability/degradation taxonomy,
  latency/failure counters, telemetry locking, and problem projection are
  implemented.
- Timeout, HTTP 429, HTTP 503, and malformed provider responses are retryable
  degraded failures; provider HTTP 400 is not retryable.
- Current telemetry covers embedding, reranking, and generation without raw
  endpoints, keys, paths, or payloads.
- Five runtime gaps are explicit: provider-aware readiness, bounded retry
  execution, restart-safe aggregate telemetry, GPU resource metrics, and
  provider execution cancellation.
- The first four are ordered S112 inputs. Cancellation remains post-MVP unless
  asynchronous MO execution is selected earlier.
- No table or migration is introduced by the audit.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_mo_resilience_telemetry_readiness_audit.py --summary

./.venv/bin/pytest -q \
  tests/test_mo_resilience_telemetry_readiness_audit.py \
  --cov=nex_mo.resilience_readiness_audit \
  --cov=run_mo_resilience_telemetry_readiness_audit \
  --cov-branch --cov-report=term-missing
```
