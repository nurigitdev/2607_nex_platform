# GB2-CA00-S20Q-P-B: Candidate Probability and Package READY Signal Design

## Status

Complete. A calibration-only candidate probability model and a package-level
READY signal contract are implemented. The existing nested selector, frozen
profile shortlist, holdout, and runtime retrieval policy remain unchanged.

## Objective

S20Q-P-A made the full retrieval pipeline repeatable, but the S20Q-P nested
selection result remained `NO_ADMISSIBLE_PROFILE`. Candidate AUC was useful,
while reducing four raw linear candidate scores to their second-highest value
lost package-level separation.

S20Q-P-B introduces a separately reviewable signal without opening the
holdout or changing an admission threshold:

1. apply one already-frozen linear profile to candidate signals;
2. fit a monotonic candidate-probability transform using inner-training data;
3. estimate the probability that at least two of four candidates are
   relevant;
4. expose bounded package diagnostics without making a READY decision;
5. keep profile selection, threshold selection, holdout access, and runtime
   activation prohibited.

## Source Design

The product implementation is
`services/nex-cx/nex_cx/retrieval_package_ready_signal.py`.

### Candidate score bridge

`score_candidate_relevance_samples()` consumes integrity-protected expanded
candidate calibration rows and one frozen profile. It emits deterministic
candidate scores with:

- dataset sample and candidate identity;
- calibration-only relevance truth;
- source profile identity;
- semantic score hash.

Candidate truth is retained only for calibration fitting and evaluation. It
is not accepted as a runtime package-signal input.

### Candidate probability model

`fit_candidate_probability_model()` implements a deterministic monotonic
Platt logistic transform:

```text
candidate score
  -> fixed centering/scaling from the training partition
  -> non-negative logistic coefficient
  -> candidate relevance probability
```

The fit is bound to the source profile, training-sample hash, model/provider
binding, regularization value, and training scope. A scope containing
`HOLDOUT` is rejected. Non-directional or unconverged fits are persisted as a
rejected result and cannot project probabilities.

The current fit is intentionally local to each future nested inner-training
partition. Fitting once over all calibration rows before cross-validation
would leak validation information and is not permitted.

### Package READY signal

`build_package_ready_signal()` accepts exactly four candidate identities and
scores. It projects candidate probabilities, then computes the
Poisson-binomial count distribution and:

```text
package READY signal = P(relevant candidate count >= 2)
```

The result also records:

- expected relevant-candidate count;
- second candidate probability;
- top-two probability mean;
- second-to-third probability gap;
- candidate probability spread;
- number of candidates with probability at least `0.5`;
- the historical second-highest raw candidate score for comparison.

This aggregation assumes conditional independence of candidate relevance
given their scores. It is an explicit approximation, not a claim that
retrieved candidates are actually independent. Its calibration quality must
be measured before it can be admitted.

## Safety Boundary

Every model and package signal carries semantic integrity hashes and an exact
binding. The package projection records:

```text
diagnostic_only = true
package_threshold = null
ready_decision = null
holdout_access_permitted = false
profile_selection_permitted = false
threshold_selection_permitted = false
runtime_activation_permitted = false
```

S20Q-P-B does not:

- modify `retrieval_calibration_nested_selection.py`;
- replace the historical second-highest package score;
- run nested selection or select a threshold;
- inspect or score the sealed holdout;
- call PostgreSQL or a remote provider;
- add a migration, API field, or runtime configuration;
- activate a retrieval confidence policy.

## Design Smoke

`run_gb2_s20qpb_candidate_probability_package_signal.py` exercises the
contract with an immutable synthetic calibration design fixture. It verifies
deterministic fitting, normalized relevant-count probability, directional
package separation, and all fail-closed flags.

```text
gb2_s20qpb_candidate_probability_package_signal=pass
positive READY probability = 0.996435
negative READY probability = 0.000000
holdout = sealed
runtime = disabled
provider calls = 0
database calls = 0
```

The numeric values above prove executable contract behavior only. They are
not production calibration evidence.

## Verification

Focused regression covering the new contract, smoke runner, existing nested
selector, S20Q-P runner, and S20Q-P-A runner:

```text
28 passed
ruff = PASS
```

NeX-CX Slice Gate:

```text
2,751 passed
statement coverage = 99.06% (minimum 95.00%)
branch coverage = 98.19% (minimum 94.00%)
new product module = 98.96% statement / 95.69% branch
design smoke runner = 98.51% statement / 94.44% branch
contract validation = 230 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Handoff

The next corrective Slice should integrate this probability transform inside
each nested inner-training fold and compare the new package signal against the
historical second-highest-score baseline on calibration OOF data only. It must
not open the holdout unless the frozen calibration admission constraints pass.

Suggested boundary:

`S20Q-P-C: Nested Candidate-Probability Package Signal Calibration`.
