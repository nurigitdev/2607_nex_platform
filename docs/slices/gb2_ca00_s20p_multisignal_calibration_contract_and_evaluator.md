# GB2-CA00-S20P: Multi-Signal Calibration Contract and Evaluator

## Outcome

S20P adds a deterministic v2 feature-package and calibration evaluator for CX
retrieval confidence. It does not replace or activate the existing S136 v1
runtime profile. S20Q remains the first Slice allowed to collect a complete
live feature package, open the sealed holdout partition, and decide whether a
v2 profile may become active.

The implementation is owned by
`services/nex-cx/nex_cx/retrieval_confidence_multisignal.py`. It reuses the
existing S136 explainable weights and the shared `nex_runtime` binary
calibration evaluator instead of adding another threshold-selection engine.

## Frozen Contract

- feature schema: `cx_retrieval_confidence_features.v2`
- feature package: `cx_retrieval_confidence_feature_package.v2`
- evaluator evidence: `cx_retrieval_confidence_multisignal_evaluation.v1`
- decision schema: `cx_retrieval_confidence_multisignal_decision.v1`
- policy: `cx_retrieval_confidence_multisignal_v2`

The four weighted features remain:

1. reranker top-1 score: `0.20`
2. reranker top-1/top-2 margin: `0.10`
3. normalized weighted-RRF score: `0.40`
4. BM25/vector channel support: `0.30`

Reranker/RRF ordering agreement, lexical-channel ratio, vector-channel ratio,
and admitted candidate count are diagnostic only. They are explicitly marked
as excluded from the composite score. Raw BM25 scores are not added directly
because they are not normalized across query or corpus changes.

## Binding and Integrity

Every feature package is bound to:

- embedding model revision;
- immutable reranker artifact revision;
- weighted retrieval policy;
- tokenizer policy;
- chunk policy.

The current admitted reranker revision shape is `hf:<40-hex>`. Mutable served
model names cannot satisfy the reranker revision field. Packages, decisions,
and evaluator results receive canonical semantic SHA-256 hash references.
Package integrity, feature weights, and the recomputed composite score are
verified before use.

## Missing-Signal Semantics

An empty admitted candidate set returns `NO_ANSWER` with
`NO_ADMITTED_CANDIDATES`. Other incomplete packages return
`LOW_CONFIDENCE`. Versioned reasons include:

- `RERANKER_SCORE_MISSING`;
- `RERANKER_MARGIN_UNAVAILABLE`;
- `RRF_NORMALIZED_SCORE_MISSING`;
- `CHANNEL_SUPPORT_SCORE_MISSING`;
- `RETRIEVAL_CHANNEL_RANK_MISSING`;
- `MODEL_OR_POLICY_BINDING_MISMATCH`.

Complete decisions use inclusive threshold comparison and return either
`COMPOSITE_SCORE_AT_OR_ABOVE_THRESHOLD` or
`COMPOSITE_SCORE_BELOW_THRESHOLD`.

## Permission Boundary

Tenant, owner, permission, authorization, subject, actor, principal, role, and
ACL fields are forbidden in the relevance feature input. Permission filtering
must finish before feature extraction. The evaluator records only the count of
already admitted candidates and never uses access breadth as relevance
confidence.

## Calibration Boundary

The evaluator requires unique sample IDs, one exact model/policy binding, one
weight set, complete feature packages, and a canonical dataset digest. It
delegates threshold selection to `evaluate_binary_score_calibration` and maps
the result to explicit reason codes. Its output always includes
`runtime_activation_permitted=false`; S20P contract vectors are not release
calibration evidence.

The calibration partition may be used in S20Q preparation. The untouched
holdout remains sealed until S20Q freezes a candidate policy and executes the
protected live acceptance.

## Verification

Focused compatibility regression:

```text
237 passed
```

NeX-CX Slice Gate:

```text
2547 passed
statement coverage: 98.98%
branch coverage: 98.16%
new v2 module statement/branch: 100% / 100%
```

Platform Slice Gate:

```text
473 passed, 8 protected skips
new v2 module statement/branch: 100% / 100%
contract validation: 228 schemas, 291 examples, 245 negative examples,
                     10 OpenAPI documents
```

The protected skips require PostgreSQL/operator environment flags and are not
needed by this deterministic Slice. No remote provider, database migration,
public API change, or holdout evaluation was performed.

## S20Q Handoff

S20Q must collect complete v2 packages from the actual permission-filtered
hybrid retrieval path, freeze the candidate threshold using only the
calibration partition, and then evaluate that immutable policy against the
holdout. Runtime activation remains fail-closed on revision, retrieval policy,
tokenizer policy, chunk policy, dataset digest, or package-integrity drift.
