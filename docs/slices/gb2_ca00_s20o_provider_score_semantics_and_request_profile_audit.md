# GB2-CA00-S20O: Provider Score-Semantics and Request-Profile Audit

## Status

`CLOSED - PROVIDER RUNTIME REVISION BINDING CORRECTION REQUIRED`

The source-backed audit, protected profile replay, focused regression, and
platform Slice Gate are complete. The initial connection failure was caused
by the workstation being associated with the wrong wireless AP, not by the
reranker. After reconnecting to the correct AP, SSH and ports `9111`, `9112`,
and `9113` were reachable and the protected replay passed.

## Audit Question

S20N rejected single-signal admission because no threshold met both frozen
constraints:

```text
false-ready rate <= 0.10
ready recall     >= 0.80
```

S20O does not change labels or weaken those constraints. It asks whether the
observed score overlap is caused by the deployed provider/request profile or
is a genuine limitation of one reranker score.

## Source-Backed Findings

The Qwen3-Reranker-4B model is instruction-aware. Its model card recommends a
task-specific instruction and recommends an English instruction for
multilingual use. Its reference score is the probability assigned to the
`yes` class against `no`.

The vLLM Qwen3 reranker example requires the original model to be served with:

```text
architectures              = Qwen3ForSequenceClassification
classifier_from_token      = [no, yes]
is_original_qwen3_reranker = true
chat template              = qwen3_reranker.jinja
```

The current NeX-MO generic rerank request contains `model`, `query`,
`documents`, and `top_n`, but no explicit instruction. The response adapter
performs structural normalization, accepts `score` or `relevance_score`, and
rounds the provider value to six decimal places. It does not transform logits
to probabilities. The current semantics label
`provider_native_relevance_0_1` is therefore less precise than the expected
Qwen3 yes-class probability semantics.

The current default `model_revision` is the mutable served model name. An
immutable model source revision must be inspected and bound before an active
calibration profile can be admitted.

The running provider was inspected as:

```text
vLLM version                       = 0.23.0
served model                       = Qwen3-Reranker-4B
runner                             = pooling
dtype                              = bfloat16
seed                               = 0
max model length                   = 4096
Qwen3ForSequenceClassification     = configured
classifier tokens                  = [no, yes]
is_original_qwen3_reranker         = true
qwen3_reranker.jinja               = configured
```

The SSH account can inspect the process arguments but cannot read the model
directory owned by the serving account. The local Hugging Face commit hash
therefore remains unconfirmed and is correctly reported as a runtime profile
correction instead of being inferred from the mutable served name.

Primary references:

- <https://huggingface.co/Qwen/Qwen3-Reranker-4B>
- <https://docs.vllm.ai/en/latest/models/pooling_models/scoring/>
- <https://github.com/vllm-project/vllm/blob/main/examples/pooling/score/qwen3_reranker_online.py>
- <https://github.com/vllm-project/vllm/blob/main/examples/pooling/score/template/qwen3_reranker.jinja>

## Audit Replay Contract

The protected runner compares two profiles without changing the product API:

| Profile | Request behavior |
| --- | --- |
| `CURRENT_DEFAULT_TEMPLATE_V1` | Existing NeX-MO `/v1/rerank` request |
| `EXPLICIT_ENTERPRISE_RETRIEVAL_V1` | Audit-only requester injects a frozen enterprise retrieval instruction |

Both profiles replay:

- all 36 frozen v1 query-document pairs;
- only the 80 v2 `CALIBRATION` pairs.

The 40-pair v2 holdout remains `SEALED_NOT_OPENED` for S20Q. Evidence stores
scores, labels, hashes, and provider identity, but no query/document text,
endpoint, credential, or raw instruction.

The possible decisions are:

```text
PROVIDER_RUNTIME_PROFILE_CORRECTION_REQUIRED
REQUEST_PROFILE_ISSUE_CONFIRMED
REQUEST_PROFILE_CONTRIBUTES_SINGLE_SCORE_LIMIT_REMAINS
GENUINE_SINGLE_SCORE_LIMITATION_CONFIRMED
```

No S20O outcome activates a runtime threshold or request profile. S20P remains
the next implementation Slice.

## Protected Live Result

The provider returned HTTP 200 from `/v1/models` and `/v1/rerank`, advertised
`Qwen3-Reranker-4B`, and ranked a relevant business document ahead of an
unrelated document. A separate request confirmed that the vLLM deployment
accepts and applies the top-level `instruction` field.

The full replay produced 232 observations:

| Dataset/profile | Status | Overlap | False-ready | Recall |
| --- | --- | ---: | ---: | ---: |
| v1 / current default | `PASSED` | `0.112785` | `8.33%` | `100%` |
| v1 / explicit instruction | `PASSED` | `0.043810` | `4.17%` | `100%` |
| v2 calibration / current default | `NO_ACCEPTABLE_THRESHOLD` | `0.244148` | `25.00%` | `90.00%` |
| v2 calibration / explicit instruction | `NO_ACCEPTABLE_THRESHOLD` | `0.090856` | `15.00%` | `92.50%` |

The explicit enterprise instruction materially reduces overlap and improves
both false-ready rate and recall, but the false-ready rate still exceeds the
frozen `10%` maximum. The score-specific assessment is therefore:

```text
REQUEST_PROFILE_CONTRIBUTES_SINGLE_SCORE_LIMIT_REMAINS
```

The primary audit decision remains:

```text
PROVIDER_RUNTIME_PROFILE_CORRECTION_REQUIRED
```

That primary decision is caused only by the missing immutable checkpoint
revision binding. The sequence-classifier override and reranker template are
confirmed. S20P may proceed with multi-signal design, but no calibration
profile may become active until the immutable revision is bound.

## Runtime Provenance

The live execution must derive, not assume, these values from the running
provider and its launch configuration:

```text
NEX_GB2_S20O_VLLM_VERSION
NEX_GB2_S20O_MODEL_SOURCE_REVISION
NEX_GB2_S20O_SEQUENCE_CLASSIFIER_OVERRIDE
NEX_GB2_S20O_QWEN3_RERANKER_TEMPLATE
```

`NEX_MO_REMOTE_RERANKER_MODEL_REVISION` must equal the inspected immutable
model source revision. The two boolean confirmations must be `1` only when the
running process actually uses the documented override and template. Missing
or false evidence produces
`PROVIDER_RUNTIME_PROFILE_CORRECTION_REQUIRED`; it is not silently accepted.

## Protected Command

The protected replay command is:

```bash
export NEX_GB2_S20O_RERANKER_LIVE=1
./.venv/bin/python scripts/smoke/run_gb2_s20o_provider_profile_audit.py \
  --summary \
  --output reports/live/gb2_ca00_s20o_provider_profile_audit.json
```

The provider URL and API key continue to come from the existing protected
NeX-MO environment and must not be placed in repository files.

## Verification

```text
focused S20K-S20O regression = 119 passed
S20O focused coverage        = statement 100.00% / branch 100.00%
platform Slice Gate          = PASS
Slice Gate regression        = 427 passed / 8 protected skips
Slice Gate statement         = 97.35%
Slice Gate branch            = 95.95%
contract validation          = PASS (228 schemas / 291 examples /
                               245 negative examples / 10 OpenAPI documents)
golden journey audit         = PASS
demo/product audit           = PASS
protected reranker replay    = PASS / 232 observations
score profile assessment     = REQUEST_PROFILE_CONTRIBUTES_SINGLE_SCORE_LIMIT_REMAINS
runtime profile assessment   = PROVIDER_RUNTIME_PROFILE_CORRECTION_REQUIRED
```

The protected evidence is stored under the ignored `reports/live/` tree. It
contains no query/document text, provider endpoint, or credential.

## Follow-Up Closure

`GB2-CA00-S20O-A` subsequently inspected the DGX-local Hugging Face metadata
and bound the current reranker profile to
`hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5`. The S20O score-profile
decision remains unchanged; only its immutable runtime revision gap is now
closed.
