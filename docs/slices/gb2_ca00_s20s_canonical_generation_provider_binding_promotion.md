# GB2-CA00-S20S: Canonical Generation Provider Binding Promotion

## Outcome

Status: `PASS / CLOSED`

Decision:

`QWEN3_5_9B_PROMOTED_TO_CANONICAL_9111_BINDING`

The platform-wide default generation binding is promoted from Qwen3.5-4B to
the admitted Qwen3.5-9B revision on the canonical generation port. This is a
binding promotion, not a repository-wide text replacement.

```text
profile     = qwen3_5_9b_bf16
alias       = general-llm-default
model       = Qwen3.5-9B
revision    = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
deployment  = dgx-qwen3-5-9b-9111
port        = 9111
precision   = BF16
reasoning   = disabled
```

Qwen3.5-4B remains explicit as `general-llm-rollback`. It is not selected by
default and is not silently removed from the catalog. The historical PCX
profile remains a separate legacy boundary.

## Canonical Binding

`services/_shared/nex_runtime/canonical_generation_binding.py` is the single
code-level source for the current generation model, immutable revision,
deployment identity, profile, precision, and reasoning mode.

The binding is consumed by:

- MO provider catalog and remote generation execution defaults.
- Canonical Compose and example environment configuration.
- CX summary and grounded-generation current runtime surfaces.
- AE, CX, and MO current acceptance and protected-live runners.
- Contract examples, provider readiness, telemetry, and observability
  projections.

The public MO model-profile contracts now admit the explicit `rollback`
candidate role. The model catalog contains six profiles: three selected
primary profiles, one generation rollback profile, one generation candidate,
and one planned generation profile.

## Immutable Calibration Evidence

The admitted answer-support policy was calibrated against the same 9B model
and revision under deployment identity `dgx-qwen3-5-9b-9116`. That historical
identity is immutable evidence and is not rewritten.

`answer_support_provider_relocation.v1.json` authorizes only this exact
endpoint relocation:

```text
source deployment = dgx-qwen3-5-9b-9116
target deployment = dgx-qwen3-5-9b-9111
model              = unchanged
revision           = unchanged
request profile    = unchanged
score semantics    = unchanged
policy/profile     = unchanged
```

The runtime fails closed if a caller attempts to change the model, revision,
request profile, score semantics, or any calibrated policy field through the
relocation boundary. Frozen S20Q/S20R evidence and replay contracts continue
to use the original 9116 identity.

## Repository Enforcement

`run_canonical_generation_provider_binding_audit.py` is part of the Full Gate
and checks the shared constant, environment example, Compose overlay, MO
primary/rollback catalog roles, remote execution defaults, protected-live
defaults, and the signed relocation amendment.

```text
canonical generation audit = 10/10 PASS
model                      = Qwen3.5-9B
port                       = 9111
```

Current product defaults may not regress to Qwen3.5-4B or port 9116 without
failing this audit. Historical evidence, explicit rollback, and legacy PCX
fixtures remain intentionally allowlisted.

## Verification

Focused verification completed before the Full Gate:

```text
contract validation             = PASS
MO canonical API surfaces       = 6/6 PASS
catalog/privacy focused tests   = 60 passed
current binding focused tests   = 20 passed
relocation focused coverage     = statement 100%, branch 100%
canonical audit                 = 10/10 PASS
```

Repository Full Gate:

```text
result                    = PASS
tests                     = 20,371 passed, 133 protected skips
pytest duration           = 2,270.10 seconds
statement coverage        = 96.74% (threshold 96.00%)
branch coverage           = 96.03% (threshold 94.00%)
product statement/branch  = 98.67% / 97.34%
harness statement/branch  = 94.18% / 92.97%
contracts                 = 230 schemas, 291 examples,
                            245 negative examples, 10 OpenAPI documents
AE Web Node regression    = 404 passed
golden transition audit   = PASS, 9 registered, 1 enforced
dependency audit          = PASS, 7/7 edges
```

## Protected Live Boundary

Protected live acceptance was executed after the operator confirmed that the
DGX was available. The run used the canonical `dgx_vllm` profile and did not
override the promoted model, revision, or deployment identity.

```text
protected DGX profile       = PASS
remote provider live smoke  = PASS
embedding                   = PASS, dimension 2560
reranking                   = PASS, Qwen3-Reranker-4B
generation                  = PASS, finish reason STOP
generation revision         = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
generation deployment       = dgx-qwen3-5-9b-9111
DGX process dtype probe     = PASS, 3/3 providers BF16 explicit
```

Protected evidence was written to the ignored `reports/live/` workspace:

- `gb2_ca00_s20s_protected_dgx_live_profile.json`
- `gb2_ca00_s20s_protected_remote_provider_live_smoke.json`
- `gb2_ca00_s20s_dgx_process_dtype_probe.json`

The profile preflight verified `/v1/models`; the generation smoke used
`reasoning_mode=disabled`; and the returned revision/deployment pair proves
that the current path used Qwen3.5-9B on port 9111 rather than the 4B rollback
or the historical 9116 calibration endpoint. The SSH process probe observed
the expected generation, embedding, and reranking models with explicit
`--dtype bfloat16` configuration.

No database migration or public API field was added by this Slice.
