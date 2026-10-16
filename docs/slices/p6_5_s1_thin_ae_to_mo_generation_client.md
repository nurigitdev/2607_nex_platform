# P6.5-S1 Thin AE-to-MO Generation Client

**Status:** IMPLEMENTED
**Date:** 2026-10-16
**Predecessor:** P6.5-CA01 Source-Backed Generation Contract Closure

## Scope

P6.5-S1 adds the internal AE port used by later semantic candidate stages:

```text
AE semantic stage
-> HttpAeMoGenerationClient
-> NeX-MO POST /api/v1/generations
-> MO provider route/retry/telemetry
-> remote generation provider
```

The Slice does not connect this client to `POST /api/v1/chat/interactions`,
create candidate records, change PostgreSQL schema, or grant model output any
runtime authority.

## Implementation

`nex_ae_api.mo_generation_client` provides:

- a narrow `AeMoGenerationClient` protocol;
- `HttpAeMoGenerationClient.generate_candidate()`;
- `check_required_mode_readiness()`;
- normalized generation/readiness result records;
- bounded error mapping to the P6.5 provider taxonomy;
- configuration and MO retry-budget validation; and
- a protected live smoke runner.

The caller supplies only semantic stage, messages, request ID, and trace ID.
The client owns the remaining wire policy:

```text
provider_capability = generation
response_format = json_object
reasoning_mode = disabled
temperature = 0.0
stream = false
X-Service-ID = nex-ae-api
service-token audience = nex-mo
```

No method accepts provider URL, provider endpoint, model path, API key, exact
model revision, response format override, reasoning override, temperature, or
streaming flag.

## Source Reconciliation

CA01 initially recorded `768 / 1536 / 2048` output tokens for
INTENT/CONTEXT/PLAN. Source inspection during S1 found that the active
`general-llm-default` MO route has `max_output_tokens=1024`; the latter two
requests would therefore fail with 422 before reaching the provider.

S1 corrects the active stage limits to:

```text
INTENT  = 768
CONTEXT = 1024
PLAN    = 1024
```

The existing MO catalog is not mutated in this Slice. A future increase must
be a versioned MO catalog entry and alias activation so persisted catalog
state, readiness, rollback, and runtime admission change together.

## Readiness

Required-mode readiness accepts only evidence where:

```text
provider_mode = live
readiness_status = READY
configured generation alias has exactly one route
route status = READY
route source = active_preflight
degraded = false
evidence cache is not stale
```

The safe projection includes alias, model revision, deployment ID, route ID,
timestamps, and cache status. It excludes endpoints and credentials.

## Timeout Policy

AE receives one deployment-projected MO service budget through
`NEX_AE_MO_GENERATION_BUDGET_SECONDS`; it does not read vLLM timeout, retry,
or Retry-After settings. The client timeout is:

```text
MO generation service budget + AE safety margin
```

The default service budget is 125 seconds and the safety margin is five
seconds, producing the 130-second AE default. Deployment configuration keeps
the service budget aligned with MO's internal provider retry policy. An
explicit shorter client timeout fails configuration before HTTP execution.

## Failure Mapping

| Condition | P6.5 code |
|---|---|
| transport unavailable or route/auth not ready | `PROVIDER_NOT_READY` |
| transport or HTTP timeout | `PROVIDER_TIMEOUT` |
| HTTP 429 | `PROVIDER_RATE_LIMIT` |
| final HTTP 5xx | `PROVIDER_SERVER_ERROR` |
| malformed success or bounded request rejection | `PROVIDER_RESPONSE_INVALID` |

MO continues to own technical provider retry. AE receives only the final
normalized result and does not retry transport inside this client.

## Privacy

Success responses are checked against the existing closed MO response shape.
Unexpected fields, provider-private keys, alias drift, correlation drift,
invalid token accounting, and invalid timestamps fail closed. The normalized
result keeps output text out of `repr`; live evidence stores only its SHA-256
digest and byte size.

## Protected Live Smoke

Run against a live NeX-MO service whose provider readiness is backed by the
actual remote providers:

```bash
NEX_AE_P65_S1_LIVE_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_p65_s1_ae_mo_generation_live_smoke.py \
  --summary --output /tmp/p65-s1-live-evidence.json
```

The smoke checks readiness first, performs one reasoning-disabled structured
generation through the AE client, validates a small JSON response, correlates
alias/revision/deployment, and emits redacted evidence below `/tmp` only.

## Verification

```text
Focused client and smoke tests: 76 passed
Focused client statement coverage: 98.29%
Focused client branch coverage: 95.45%
P5/P6/P6.5 selected regression: 185 passed
AE Slice Gate: PASS (308 test files, 4/4 commands)
AE Slice Gate regression: 4,020 passed, 10 protected-smoke skips
AE Slice Gate statement coverage: 98.61%
AE Slice Gate branch coverage: 96.82%
Contract validation: PASS (174 schemas, 7 OpenAPI documents)
Protected live provider smoke: PASS (8/8 checks)
Observed model revision: Qwen3.5-4B
Observed route source: active_preflight
Reasoning mode: disabled
```

Sanitized live evidence is stored at:

```text
reports/live/p65-s1-ae-mo-generation-live.json
```

The smoke launched the repository NeX-MO service temporarily in live mode,
verified embedding/reranking/generation readiness against the connected DGX,
then sent the semantic generation request through the AE client and MO API.
The temporary service was stopped after evidence collection.

## Exit

P6.5-S1 is closed: focused regression is green and one actual MO live provider
response was observed through the internal AE contract. The committed evidence
contains no endpoint, API key, service token, prompt text, or output text.
