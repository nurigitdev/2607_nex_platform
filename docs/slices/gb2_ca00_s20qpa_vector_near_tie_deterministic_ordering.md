# GB2-CA00-S20Q-P-A: Vector Near-Tie Deterministic Ordering

## Status

Complete. The vector candidate and weighted-RRF input paths now use one bounded
near-tie ordering rule. Actual PostgreSQL and live provider evidence changed the
five-run full retrieval pipeline result from `UNSTABLE` to `STABLE` without
rounding, replacing, or hiding the raw similarity scores.

This Slice resolves retrieval repeatability only. Dataset v4 package-level
calibration remains `REJECTED`, the nested selection remains
`NO_ADMISSIBLE_PROFILE`, and HOLDOUT remains sealed.

## Objective

S20Q-P observed eight vector-rank changes and eight corresponding RRF drifts in
2,560 repeated candidate comparisons. Candidate membership, BM25, reranker
scores, and final rank were stable. The changing pair had score differences
between approximately `0.00023` and `0.00092`, so exact floating-point ordering
turned provider numeric variation into discrete vector-rank changes.

S20Q-P-A must:

1. stabilize only bounded vector near ties;
2. preserve meaningful score differences and every raw vector score;
3. apply the same rule at vector collection and hybrid-ranking validation;
4. avoid relaxing the repeatability evaluator;
5. keep calibration admission, HOLDOUT access, and runtime activation closed.

## Design

`nex_cx.vector_ordering` owns the policy:

```text
policy id          = cx_vector_near_tie_stable_identity_v1
maximum score gap  = 0.001
group anchor       = highest raw score in the group
stable order       = content_object_id, chunk_id, vector_index_id when present
raw score mutation = prohibited
```

Candidates are first ordered by raw score. A near-tie group includes only
candidates no more than `0.001` below the group's highest score. This anchored
rule prevents adjacent candidates from chaining into a group whose total score
span exceeds the limit. Members of the bounded group then use persistent
identity order.

The rule is applied in both locations that previously performed independent
exact-score sorting:

- `vector_candidates.collect_fresh_vector_candidates`, before global candidate
  ranks and the candidate limit are applied;
- `hybrid_ranking._channel_candidates`, before vector ranks enter weighted RRF.

Lexical ranking, RRF weights, `rrf_k`, reranker behavior, ranking policy ID,
provider score semantics, and database structures are unchanged. This is a
determinism correction to the existing policy, not a new calibration profile.

## Regression Verification

Focused tests cover score inversion, the exact policy boundary, non-transitive
group prevention, global vector candidate ordering, hybrid RRF input ordering,
fail-closed smoke checks, and separation of repeatability from calibration
admission.

```text
focused tests = 127 passed
vector_ordering = 100% statement / 100% branch
S20Q-P-A runner = 100% statement / 100% branch
ruff = PASS
```

NeX-CX Slice Gate:

```text
2,742 passed
statement coverage = 99.07% (minimum 95.00%)
branch coverage = 98.26% (minimum 94.00%)
vector_ordering scope = 100% statement / 100% branch
S20Q-P-A runner scope = 100% statement / 100% branch
contract validation = 230 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Protected Live Evidence

The protected runner used the actual `nex_cx_test` database and immutable live
provider bindings:

```text
database / role = nex_cx_test / nex_cx_user
migrations = 23 planned / 0 applied / 23 current
embedding revision = hf:5cf2132abc99cad020ac570b19d031efec650f2b
reranker revision = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
calibration scenarios = 80
packages per repeat = 160
candidates per repeat = 640
pipeline repeats = 5
embedding calls = 1,440 successful / 0 failed
reranking calls = 800 successful / 0 failed
candidate comparisons = 2,560
cleanup = PASS
```

Repeatability changed as follows:

| Measurement | S20Q-P | S20Q-P-A |
| --- | ---: | ---: |
| Pipeline status | `UNSTABLE` | `STABLE` |
| Vector-rank changes | 8 | 0 |
| RRF score drifts | 8 | 0 |
| Candidate membership changes | 0 | 0 |
| Final-rank changes | 0 | 0 |
| Maximum RRF delta | `0.01129032` | `0` |
| Maximum vector similarity delta | `0.00326445` | `0.00321917` |

The similarity delta remains visible and below the existing `0.005` numeric
tolerance. The ordering correction removes discrete rank changes; it does not
claim that live model arithmetic is bit-exact.

The local redacted evidence is:

`reports/live/gb2_ca00_s20qpa_vector_near_tie_ordering.json`

## Safety Boundary

S20Q-P-A does not:

- change or quantize provider similarity scores;
- treat score differences above `0.001` as ties;
- relax rank, score, RRF, or provider repeatability tolerances;
- alter BM25, weighted RRF, reranking, or permission filtering;
- add a database migration or API field;
- score the HOLDOUT partition;
- approve a profile, threshold, or runtime calibration policy.

## Handoff

Vector/RRF repeatability is no longer the blocker. The next corrective Slice
should address package-level READY signal semantics using calibration data only.
It must preserve this ordering policy and keep HOLDOUT sealed until a frozen
package feature/profile shortlist passes nested calibration.
