# GB2-CA00-S20M: Live Score Collection and Repeatability

## Scope

S20M executes the admitted 120-pair reranker calibration dataset twice against
the canonical remote reranker. The protected run verifies the provider binding,
complete pair coverage, finite bounded scores, numeric repeatability, and rank
repeatability without persisting request text, provider endpoints, or
credentials.

The live runner is:

- `scripts/smoke/run_gb2_s20m_reranker_repeatability_live.py`

## Initial finding

The first live execution against the prior serving profile was stopped
fail-closed. Repeated requests produced a maximum absolute score delta of
`0.002392` and rank changes. That result was not admitted as stable calibration
evidence and led to the S20M-A numeric repeatability investigation.

## Corrected serving-profile rerun

After the operator changed the Qwen3-Reranker-4B vLLM serving profile, the
protected rerun confirmed:

| Check | Result |
| --- | ---: |
| vLLM server version | `0.23.0` |
| model revision | `Qwen3-Reranker-4B` |
| admitted pairs | `120` |
| repeats | `2` |
| observations | `240` |
| maximum absolute score delta | `0.0` |
| rank inversions | `0` |
| protected result | `PASS` |

The server-reported model context limit remained `4096`. The run used the
canonical `/v1/rerank` request shape and retained the strict S20M score-delta
gate of `0.000001`.

Protected evidence is written under the ignored `reports/live/` tree. The
evidence stores pair identifiers, labels, scores, ranks, model revision, and
deployment identity only. It does not store query/document text, the provider
URL, or the API key.

## Regression

The focused repeatability suite passed:

```text
30 passed in 0.95s
```

The suite covers shared response validation, incomplete coverage, identity
drift, malformed scores, score/rank drift, redaction, the two-repeat S20M gate,
and the five-repeat S20M-A policy.

The Repository Checkpoint Gate also passed:

| Gate result | Value |
| --- | ---: |
| tests | `18,240 passed / 132 skipped` |
| statement coverage | `98.57%` |
| branch coverage | `97.15%` |
| contract validation | `PASS` |
| golden journey transition audit | `PASS` |
| demo/product dependency audit | `PASS` |

Checkpoint coverage evidence is recorded at
`reports/quality/gb2-ca00-s20m-checkpoint.coverage.json`.

## Decision

S20M is closed. Its strict repeatability contract passes on the corrected
serving profile, and downstream calibration may consume only the evidence from
that profile and provider binding.
