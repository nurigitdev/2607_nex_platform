# GB2-CA00-S20Q-G: Calibration-Only Feature Selection, Weighting, and Threshold Freeze

## Status

`STOPPED_FAIL_CLOSED`

The calibration-only selector and protected evidence path are implemented and
verified. No candidate policy was frozen because none satisfied the existing
safety constraints. The v3 holdout remains sealed and the original S20Q live
holdout acceptance is not authorized to continue.

## Scope

S20Q-G adds a deterministic, calibration-only decision boundary that:

- consumes text-free, integrity-protected package feature rows;
- compares the two directional current features and three directional
  corrected features identified by S20Q-F;
- evaluates one- to three-feature subsets and `0.10` weight increments;
- uses five-fold scenario-grouped cross-validation;
- preserves `false-ready <= 0.10` and `ready recall >= 0.80`;
- applies the S20M-A numeric tolerance in label-adverse worst-case scoring;
- binds any candidate to immutable provider revision, dataset, retrieval,
  tokenizer, and chunk-policy lineage;
- forbids runtime activation until the untouched holdout passes later.

The existing `cx_retrieval_confidence_multisignal_v2` runtime schema and active
policy are unchanged.

## Implementation

### Text-free feature projection

`retrieval_confidence_candidate_diagnostics.py` now projects each mixed
candidate package into an integrity-protected numeric calibration row. Query
text, candidate text, endpoint, credential, permission, and ownership values
are not projected.

### Candidate selector and freezer

`retrieval_confidence_candidate_selection.py` implements deterministic subset,
weight, grouped-fold, threshold, repeatability, and immutable freeze logic.
It emits either:

- `FROZEN` with a hashed `CANDIDATE_FROZEN` policy whose runtime activation is
  prohibited; or
- `NO_ACCEPTABLE_POLICY` with no threshold and no frozen policy.

Fold training may use its best-effort threshold only to measure out-of-fold
behavior. The complete calibration set and OOF aggregate must still satisfy
the frozen safety constraints; those constraints are never weakened.

### Protected runner

`run_gb2_s20qg_candidate_policy_freeze.py` performs actual CX PostgreSQL and
live embedding/reranking collection, admits the S20M-A repeatability evidence
and S20O-A immutable revision evidence, runs selection, preserves the sealed
holdout, verifies restart readback, and removes all temporary rows.

## Protected Result

Execution environment:

```text
PostgreSQL = nex_cx_user@nex_cx_test
embedding provider = live / 200 calls
reranking provider = live / 40 calls
reranker artifact revision = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
repeatability profile = reranking-qwen3-4b-numeric-repeatability-v1
repeatability observations = 600 across 5 repeats
numeric tolerance = 0.0005
holdout provider calls = 0
restart readback = PASS
zero-residue cleanup = PASS
```

Search result:

```text
calibration packages = 40 / 20 scenario pairs
candidate feature profiles = 455
admissible profiles = 0
rejection = FULL_CALIBRATION_THRESHOLD_UNAVAILABLE (455)
frozen policy = none
```

Final best-effort diagnostic only:

```text
features = reranker_score_spread, reranker_second_score
weights = 0.20, 0.80
balanced accuracy = 0.70
false-ready rate = 0.20
ready recall = 0.60
required false-ready rate <= 0.10
required ready recall >= 0.80
```

The best-effort result fails both safety limits. Freezing its threshold would
create excessive false acceptance while rejecting too many valid packages.
It is diagnostic evidence only and cannot become a runtime policy.

Local protected evidence:

```text
path = reports/live/gb2_ca00_s20qg_candidate_policy_freeze.json
file sha256 = 84ae5cff08437e93762b249560637980f28910f339ce096482e842845c2b4a09
sample set hash = sha256:91c713b58ff31cb5258e38a6de46c1a34faedb5cc0cbe774e892d6d66c1aa2a6
selection hash = sha256:c561d2ab8fece3a2881e1fe3446be016372b6a21a8b1ad4a81b44963a1275f5b
```

The ignored `reports/` artifact remains local. This document records its
reviewed bounded result.

## Verification

Focused unit and runner regression:

```text
42 passed
new boundary statement/branch coverage = approximately 99% / 99%
```

NeX-CX Slice Gate:

```text
regression tests = 2,629 passed
statement coverage = 99.03% (minimum 95.00%)
branch coverage = 98.23% (minimum 94.00%)
contract validation = 229 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Stop Decision

S20Q-G must not be declared policy-freeze complete. Proceeding to the original
S20Q would either open the holdout without a frozen policy or require weakening
the frozen safety constraints; both are prohibited.

The next work requires a separately reviewed corrective Slice. Its scope should
start with full retrieval-pipeline repeatability and package-feature semantics,
then introduce or transform only runtime-available relevance signals. Dataset
labels, safety thresholds, and the sealed holdout must remain unchanged.
