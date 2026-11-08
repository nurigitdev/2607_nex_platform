# GB2-CA00-S20Q-B: Calibration Feature Discriminativeness and Package Semantics Audit

## Outcome

`S20Q-B` is complete as a calibration-only diagnostic Slice. It does not
admit a runtime confidence profile. The actual PostgreSQL and live-provider
evidence proves that the current four-feature package cannot satisfy the
unchanged group-CV safety constraints, even when all weight restrictions are
removed.

The final audit execution kept the holdout sealed and recorded:

```text
database             = nex_cx_test / nex_cx_user
calibration groups   = 20
calibration packages = 40
embedding provider   = live / exact admitted model
reranker revision    = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
provider failures    = 0
restart readback     = exact
cleanup              = complete
runtime activation   = prohibited
holdout access       = prohibited
```

## Feature Audit

The audit uses only numeric features and public sample identities. Query and
document text are not projected into evidence.

| Feature | Higher-is-ready AUC | Paired result | Univariate gate |
| --- | ---: | --- | --- |
| reranker score | `0.8725` | positive higher `19/20` | `PASSED` |
| reranker margin | `0.0275` | negative higher `19/20` | `NO_ACCEPTABLE_THRESHOLD` |
| normalized RRF | `0.33625` | negative higher `10/20`, ties `6/20` | `NO_ACCEPTABLE_THRESHOLD` |
| channel support | `0.575` | ties `17/20` | `NO_ACCEPTABLE_THRESHOLD` |

Normalized RRF and channel support have Pearson correlation `0.99744782`.
They are effectively duplicate rank/channel observations in this package
shape rather than independent confidence evidence.

## Weight Search

The canonical constrained search evaluated 764 profiles:

```text
admissible profiles   = 0
best false-ready rate = 0.15
best ready recall     = 0.80
best balanced accuracy= 0.825
best weights          = score 0.25 / margin 0.05 /
                        RRF 0.15 / channel 0.55
```

The diagnostic unrestricted search evaluated 1,771 profiles. Zero weights,
100% single-feature weight, and no reranker/retrieval group minimum were
allowed only for diagnosis:

```text
admissible profiles   = 0
best false-ready rate = 0.15
best ready recall     = 0.80
best balanced accuracy= 0.825
best weights          = score 0.05 / margin 0.00 /
                        RRF 0.35 / channel 0.60
```

The unrestricted result is not an activation candidate. It demonstrates that
the rejection is not caused only by the canonical minimum-weight constraints.

Repeated live executions did not select the same best profile, and one
pre-audit compatibility execution selected a calibration profile that later
failed holdout while both audit-only replays selected no acceptable profile.
All runs agreed that no profile was admissible end to end. This variability is
additional evidence against activation and must be included in the next
package redesign/repeatability closure.

## Package Semantics Finding

The current live collector creates two independently scoped packages for one
query:

1. a positive package containing two expected-ready documents;
2. a negative package containing two expected-low-confidence documents.

This makes top-1/top-2 margin structurally inverted. Two relevant documents
usually receive close reranker scores, while a hard-negative/easy-negative
pair usually has a larger gap. Within-scope RRF normalization also places the
top candidate near `1.0` regardless of relevance. The package therefore
measures the composition of a same-label pair rather than confidence in the
mixed candidate set seen by the production runtime.

No threshold relaxation, label rewrite, feature sign inversion, or runtime
activation was performed.

## Holdout Hygiene

An initial compatibility execution inherited the original S20Q behavior. In
that run the constrained calibration happened to select a profile and opened
the v2 holdout; the holdout rejected the profile and no active profile was
created. That result was not used to choose S20Q-B weights or alter feature
semantics.

The runner now has an explicit audit-only boundary. The canonical S20Q-B
execution proves `CALIBRATION_AUDITED_HOLDOUT_SEALED`. Because the existing v2
holdout outcome has nevertheless been observed, a future redesigned package
must use a new dataset/holdout version for unbiased admission.

## Required Decision Before S20Q-C

The recommended corrective direction is a package-level dataset that mirrors
production retrieval:

- one retrieval over a mixed permitted candidate set;
- answerable and unanswerable query groups labelled at package level;
- no positive-only versus negative-only document scoping;
- features with independent confidence meaning rather than rank-position
  duplication;
- a new immutable calibration/holdout split and dataset digest.

This is a canonical dataset and feature-semantics change, not a small weight
adjustment. Implementation stops at this decision boundary.

## Verification

```text
focused regression       = 83 passed
new/changed core modules = 100.00% statement / 100.00% branch
actual audit-only smoke  = PASS
PostgreSQL               = actual nex_cx_test
live embedding/reranker  = PASS / zero provider failures
holdout in final audit   = sealed
NeX-CX Slice Gate        = PASS
Slice Gate regression    = 2,584 passed
Slice Gate statement     = 99.00%
Slice Gate branch        = 98.22%
contract validation      = PASS (228 schemas / 291 examples /
                           245 negative examples / 10 OpenAPI documents)
golden journey audit     = PASS
demo/product audit       = PASS
```

Protected evidence is stored under ignored `reports/live/` and contains no
provider credential, endpoint, database password, query text, or document
text.
