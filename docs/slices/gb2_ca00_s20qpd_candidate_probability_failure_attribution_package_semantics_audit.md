# GB2-CA00-S20Q-P-D: Candidate-Probability Failure Attribution and Package Semantics Audit

## Status

Complete. The Dataset v4 CALIBRATION evidence was replayed without provider or
database calls. Candidate probability remained directionally useful, but the
Poisson-binomial `P(relevant count >= 2)` projection did not preserve that
signal at package level. HOLDOUT remains sealed and runtime activation remains
prohibited.

## Boundary

This Slice is diagnostic only. It does not change:

- Dataset v4 labels, folds, or immutable digest;
- embedding or reranker model revision;
- retrieval, ranking, tokenizer, or chunk policy;
- the P-C candidate probability model;
- admission thresholds or HOLDOUT state.

The audit fits each frozen candidate profile on the complete CALIBRATION
partition for failure attribution only. Those fits are not eligible for model
or threshold selection.

## Findings

The four frozen profiles produced the following diagnostics:

| Profile | Candidate AUC | Package AUC | Paired direction | Unobserved count mass |
| --- | ---: | ---: | ---: | ---: |
| `reranker-only-v1` | `0.73329427` | `0.44328125` | `0.45` | `0.47408425` |
| `s20qh-three-signal-balanced-v1` | `0.73973958` | `0.42968750` | `0.50` | `0.49757154` |
| `s20qk-three-signal-channel-v1` | `0.74470052` | `0.44203125` | `0.50` | `0.50114147` |
| `s20qi-expanded-channel-v1` | `0.75916667` | `0.52187500` | `0.5375` | `0.49951625` |

Every package-level full-calibration diagnostic returned
`NO_ACCEPTABLE_THRESHOLD`. Candidate relevance is directional, but the
conditional-independence projection places about half of its probability mass
on relevant counts that Dataset v4 package semantics do not observe. This is
not accepted as proof that real retrieval candidates are independent.

The authoritative attribution is:

```text
decision = DEPENDENCE_ROBUST_PACKAGE_SCORE_REQUIRED
dataset or label change = not authorized
model revision change = not authorized
holdout = SEALED_NOT_OPENED
runtime activation = prohibited
```

## Implementation

- `nex_cx.retrieval_package_probability_audit` validates package semantics and
  records candidate/package AUC, Brier score, log loss, calibration error,
  pair direction, count-distribution mismatch, and unobserved count mass.
- `run_gb2_s20qpd_package_probability_failure_audit.py` consumes redacted P-C
  evidence and reconstructs candidate observations without new provider calls.
- The next contract must use a dependence-robust package ordinal score. It may
  not consume candidate truth at runtime or open HOLDOUT.

## Verification

```text
focused regression = 8 passed
protected evidence replay = PASS
provider calls = 0
database calls = 0
holdout calls = 0
```
