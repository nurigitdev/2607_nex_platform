# GB2-CA00-S20M-A: Provider Numeric Repeatability Calibration

## Purpose

S20M-A separates provider numeric variation from relevance-quality decisions
before threshold calibration. It repeats the complete 120-pair dataset five
times and classifies rank exchanges as:

- cross-label exchange: fail closed;
- same-label near-tie exchange: observe;
- same-label non-near exchange: fail closed.

The implementation is shared by S20M-A and its focused tests:

- `scripts/smoke/reranker_repeatability.py`
- `scripts/smoke/run_gb2_s20ma_provider_numeric_repeatability.py`

## First measurement and stop decision

The first five-repeat run against the prior serving profile completed 600
observations but failed closed:

| Measurement | Result |
| --- | ---: |
| maximum pair score range | `0.002837` |
| mean pair score range | `0.000745275` |
| p95 pair score range | `0.001822` |
| p99 pair score range | `0.002523` |
| provisional tolerance candidate | `0.004` |
| cross-label rank exchanges | `1` |
| same-label near-tie exchanges | `1` |

The cross-label exchange prevented admission. The provisional `0.004`
tolerance was not frozen.

## Corrected serving-profile measurement

The operator changed the vLLM serving profile and S20M-A was rerun against the
same admitted dataset and provider identity:

| Measurement | Result |
| --- | ---: |
| repeats | `5` |
| observations | `600` |
| maximum pair score range | `0.0` |
| cross-label rank exchanges | `0` |
| same-label near-tie exchanges | `0` |
| same-label non-near exchanges | `0` |
| candidate score-delta tolerance | `0.0005` |
| protected result | `PASS` |

`0.0005` is the policy quantum and therefore the minimum candidate tolerance;
it is not an observed drift allowance. The corrected provider produced
identical scores and rankings across all five repeats.

## Safety boundary

- Positive/negative rank reversal remains fail-closed.
- Dataset labels are not changed to fit provider output.
- A candidate profile is bound to model revision, deployment ID, request shape,
  retrieval policy, score semantics, dataset ID, and dataset digest.
- Query/document text, provider endpoints, and credentials are rejected from
  persisted evidence.
- A future model, revision, request template, or serving-profile change requires
  repeatability measurement again before threshold calibration.

## Decision

S20M-A is closed with candidate numeric tolerance `0.0005`. The corrected
serving profile also passed the original stricter S20M two-repeat gate with
zero score delta and zero rank inversions. The subsequent Repository Checkpoint
Gate passed with `18,240 passed / 132 skipped`, statement coverage `98.57%`, and
branch coverage `97.15%`.
