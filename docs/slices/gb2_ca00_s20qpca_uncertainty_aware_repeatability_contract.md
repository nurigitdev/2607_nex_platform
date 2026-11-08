# GB2-CA00-S20Q-P-C-A: Uncertainty-Aware Repeatability Contract

## Status

Complete. The fixed near-tie threshold expansion was rejected after actual live
evidence crossed both `0.001` and the experimental `0.005` boundary. The P-A
ordering policy remains unchanged at `0.001`; repeatability now preserves raw
intermediate changes while separating bounded numeric-equivalent exchanges
from unbounded semantic instability.

## Problem and Decision

The first P-C run observed a vector score gap moving from `0.00096785` to
`0.00105847`. Expanding the ordering boundary to `0.005` produced another live
crossing from `0.00446380` to `0.00598370`. In both cases candidate membership,
BM25, reranker score, and final rank were unchanged while vector rank and RRF
changed eight times.

No finite stateless threshold can remove every boundary crossing without
eventually treating meaningful score gaps as ties. The accepted contract is:

1. preserve raw vector-rank and RRF change counts;
2. classify an exchange as bounded only when candidate membership, BM25 rank,
   final reranker rank, and admitted score tolerances all remain valid;
3. record bounded and unbounded counts separately;
4. fail closed when any unbounded exchange exists;
5. require an admitted candidate-probability profile to keep package READY
   decisions invariant across all five repetitions;
6. keep HOLDOUT and runtime activation closed regardless of this diagnostic.

The repeatability schema and policy advance to:

```text
schema = cx_retrieval_pipeline_repeatability.v2
policy = cx_uncertainty_aware_full_retrieval_pipeline_repeatability_v2
numeric equivalence = cx_vector_similarity_numeric_equivalence_v1
vector similarity tolerance = 0.005
P-A ordering policy = cx_vector_near_tie_stable_identity_v1
P-A ordering boundary = 0.001
```

## Evidence

The final protected run passed with no raw exchanges and a maximum vector
similarity delta of `0.00321482`. It used actual `nex_cx_test` and 2,240 live
provider calls with zero failures.

The previously failing live run was replayed through the v2 analyzer without
new provider calls:

```text
raw vector-rank changes = 8
bounded vector exchanges = 8
unbounded vector changes = 0
raw RRF drifts = 8
bounded RRF drifts = 8
unbounded RRF drifts = 0
final-rank changes = 0
maximum vector delta = 0.00329022
first observed stage = VECTOR_RANK
first unstable stage = none
status = STABLE
```

The raw changes are visible evidence, not discarded noise. A score delta above
`0.005`, membership drift, BM25-rank drift, reranker drift, or final-rank drift
continues to produce `UNSTABLE`.

The current calibration has no admitted profile, so package READY
repeatability is explicitly:

```text
status = NOT_APPLICABLE_PROFILE_NOT_ADMITTED
admission permitted = false
runtime activation = false
holdout access = false
```

## Verification

```text
focused regression = 155 passed before coverage hardening
final NeX-CX Slice Gate = 2,766 passed
statement coverage = 99.04%
branch coverage = 98.11%
repeatability analyzer = 100% statement / 100% branch
P-C-A runner = 100% statement / 100% branch
contract validation = PASS
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

No database migration, API field, model revision, ranking weight, threshold,
or HOLDOUT decision changed in this Slice.
