# GB2-CA00-S20N: Single-Signal Calibration and Holdout Decision

## Status

`CLOSED - MULTI_SIGNAL_REQUIRED`

## Scope

S20N consumes the admitted S20M-A numeric-repeatability evidence without
calling a remote provider. It selects a reranker threshold from the 80-pair
calibration partition only, freezes that outcome, and opens the 40-pair
holdout partition only when calibration produces an acceptable threshold.

The implementation is:

- `nex_runtime.model_calibration.evaluate_binary_score_threshold`;
- `scripts/quality/run_gb2_s20n_single_signal_calibration.py`.

The shared evaluator adds fixed-threshold confusion metrics, score overlap,
and 95% Wilson intervals. Existing threshold-selection and active-profile
behavior remain unchanged.

## Evidence Admission

The offline runner admits only a passed S20M-A candidate profile bound to:

```text
capability          = reranking
model               = Qwen3-Reranker-4B
request shape       = rerank
score semantics     = provider_native_relevance_0_1
retrieval policy    = weighted_rrf_vector_bm25_v1
dataset             = s136-reranker-relevance-public-v2
dataset sha256      = a59c47a2401004897ab5f03cd911f76aee09e81d3df9c59d799b553175665899
```

It revalidates all 600 pair/repeat observations, model and deployment
identity, partition and label binding, finite bounded scores, complete
coverage, and the admitted `0.0005` numeric-repeatability tolerance. The five
scores for each pair are reduced by median before calibration.

## Calibration Decision

The canonical constraints were not changed:

```text
false-ready rate <= 0.10
ready recall     >= 0.80
```

No calibration threshold satisfied both constraints. The best-effort
diagnostic result was:

| Metric | Result |
| --- | ---: |
| threshold | `0.3742185` |
| true ready / false low | `36 / 4` |
| false ready / true low | `10 / 30` |
| ready recall | `0.90` |
| false-ready rate | `0.25` |
| balanced accuracy | `0.825` |
| ready precision | `0.7826087` |
| score overlap width | `0.244148` |

The uncertainty evidence is:

| Metric | Point estimate | 95% Wilson interval |
| --- | ---: | ---: |
| false-ready rate | `0.25` | `[0.14187119, 0.40193961]` |
| ready recall | `0.90` | `[0.76948225, 0.96042047]` |

The recall point estimate passes, but the false-ready point estimate is 2.5
times the admitted maximum. Labels and constraints were not adjusted to fit
provider output.

## Holdout Boundary

Because calibration produced `NO_ACCEPTABLE_THRESHOLD`, no candidate
threshold was frozen for admission and the holdout score distribution was not
evaluated. The protected decision records:

```text
decision               = MULTI_SIGNAL_REQUIRED
holdout status         = SEALED_NOT_OPENED
threshold reselected   = false
diagnostic threshold   = 0.3742185
freeze record hash     = sha256:557194dc0fd4ec8b0a5493b5feb1f1f7e350983a1200708a7c48b7145af947f4
```

The diagnostic threshold is not an admitted runtime threshold. S20P may use
the calibration partition to fit a multi-signal policy, and S20Q remains the
first stage allowed to evaluate that frozen policy against holdout groups.

## Verification

```text
focused regression       = 45 passed
actual S20M-A evidence   = PASS / 600 observations admitted
offline S20N execution  = PASS / MULTI_SIGNAL_REQUIRED
platform Slice Gate     = PASS
Slice Gate regression   = 472 passed / 8 protected skips
changed code statement  = 100.00%
changed code branch     = 100.00%
contract validation     = PASS (228 schemas / 291 examples /
                          245 negative examples / 10 OpenAPI documents)
golden journey audit    = PASS
demo/product audit      = PASS
remote provider call    = not required / not performed
```

Protected evidence is stored under the ignored `reports/live/` tree, and the
coverage report is stored under ignored `reports/quality/`. Neither report
contains query/document text, provider endpoints, or credentials.
