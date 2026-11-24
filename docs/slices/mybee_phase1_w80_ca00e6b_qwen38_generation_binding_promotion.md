# W80-CA00E.6B Qwen3.8 Generation Binding Promotion

## Status

`CLOSED` on 2026-11-24.

W80-CA00E.6B promotes the general generation provider from Qwen3.5-9B to
Qwen3.8-Flash-Next without changing the provider endpoint, public generation
API, timeout budgets, or database schema.

## Canonical Binding

```text
profile     = qwen3_8_flash_next_fp4
alias       = general-llm-default
model       = Qwen3.8-Flash-Next
revision    = hf:fc694b54fb0174e0913e6adf86691ef85a4ead47
deployment  = dgx-qwen3-8-flash-next-9111
port        = 9111
runtime dtype = BF16
reasoning   = disabled
```

The model artifact is the DGX FP4 package identified by the immutable model
revision. `precision=BF16` continues to mean the vLLM runtime dtype verified by
MO runtime observation and process probes; it is not a new weight-quantization
field.

`services/_shared/nex_runtime/canonical_generation_binding.py` remains the
single code-level owner for the active model, revision, deployment, port,
runtime precision, and reasoning mode. Compose defaults, `.env.example`, MO
provider catalog, readiness probes, and current W70/W80 installed-journey
runners consume that binding.

## Compatibility Decision

- Qwen3.5-9B remains an explicit non-selected rollback profile.
- Qwen3.5-4B is retired from the active catalog and remains only in immutable
  historical evidence.
- Existing Qwen3.5-9B answer-support calibration, relocation, holdout, and
  operations evidence is not rewritten.
- The new Qwen3.8 revision cannot reuse the historical answer-support
  relocation. CX rejects it fail-closed until a separate calibration and
  activation boundary admits this revision.
- General IA/PA semantic generation and installed product planning use the new
  canonical binding immediately; this does not activate the new model for the
  answer-support policy.

## Provider Preflight

The provider was checked before repository promotion:

```text
TCP 192.168.20.243:9111         = PASS
GET /v1/models                  = PASS
served model                    = Qwen3.8-Flash-Next
artifact root                   = nvidia/Qwen3.8-Flash-Next-FP4-Local
max model length                = 262144
reasoning-disabled JSON probe   = PASS, 2.238 seconds
INTENT / CONTEXT / PLAN probes  = PASS, mean 1.294 seconds
five-repeat INTENT probe        = PASS, one stable payload
five-repeat latency             = 0.526-0.789 seconds
reasoning tokens                = 0
```

These timings are connectivity and contract evidence, not a new latency SLO.
The existing bounded generation timeout hierarchy remains unchanged.

## Verification

Focused provider, canonical-binding, and answer-support boundary tests passed.
The historical answer-support relocation is valid under its historical
canonical binding and rejected under the new active binding.

```text
MO Slice Gate
  tests                  = 1,332 passed / 6 protected skips
  statement / branch     = 99.80% / 99.39%

CX Slice Gate
  tests                  = 3,423 passed
  statement / branch     = 99.29% / 98.53%

AE Slice Gate
  tests                  = 6,998 passed / 53 protected skips
  statement / branch     = 96.46% / 94.72%
  product coverage       = 97.07% / 95.01%

contract validation      = PASS, 277 schemas / 322 examples
golden transition audit  = PASS, 10 registered / 1 enforced
dependency audit         = PASS, 7/7 edges
```

The existing non-blocking Starlette/httpx and Python SQLite datetime
deprecation warnings remain unchanged.

## Exact-Head Protected Installed Acceptance

The exact-head installed journey was executed from commit
`19e0b59364bf73c75c6d5b3bd6676842705ef3b6` with release-set digest
`sha256:ce0394ac78df97f5891b4414845bf6f64beb82eb827ba5e77c39f2adc0756132`.

The first execution overlapped another DGX workload. Its first two accepted
generation requests took `90.115` and `82.919` seconds, so the browser reached
the existing 180-second semantic-submit budget before PLAN generation. The
failure path dropped all eight isolated PostgreSQL schemas and reported zero
residue. No timeout or product contract was changed from this observation.

The same exact-head journey was then repeated while the DGX was idle:

```text
installed journey                 = PASS
actual PostgreSQL / OpenBao       = PASS / PASS
actual RustFS / remote generation = PASS / PASS
authenticated Playwright          = PASS
restart recovery                  = PASS
zero residue                      = PASS
generation requests               = 8
INTENT / CONTEXT / PLAN           = 2 / 2 / 4
embedding / reranking requests    = 0 / 0
generation latency min / mean     = 6.348 / 8.540 seconds
generation latency p95 / max      = 11.187 / 11.187 seconds
```

All eight responses identified the admitted immutable revision and completed
with `STOP` without an application error. The journey produced two distinct
posted Journals, two AllocationBatches, two AgentResults, six approval
decisions, and 17 retained screen-evidence files. After the installed service
restart, the authoritative result, business references, and result hash were
recovered without duplicate domain rows or pending queues.

The idle result leaves substantial margin under the existing 180-second
semantic-submit budget. This Slice therefore keeps that budget unchanged and
records co-resident DGX load as an operational latency signal rather than
masking it with a larger acceptance timeout.

## Scope

This Slice adds no database migration and no public API field. Registry push
is not part of the acceptance. Exact-head OCI packaging and protected installed
live-journey evidence are produced after the source commit so that image and
runtime evidence bind to an immutable repository head.
