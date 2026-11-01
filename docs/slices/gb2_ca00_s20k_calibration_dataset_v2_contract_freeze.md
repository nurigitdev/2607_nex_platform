# GB2-CA00-S20K Calibration Dataset v2 Contract Freeze

## Status

`CLOSED`

## Scope

S20K freezes the source-backed admission contract for the expanded reranker
calibration dataset. It does not author the 120 labelled pairs and does not
call a remote provider.

The historical v1 dataset remains an immutable regression asset:

```text
path        = scripts/smoke/data/s136_reranker_calibration_v1.json
dataset id  = s136-reranker-relevance-public-v1
file sha256 = 743bee364a8f576b857380d3e6f0dffb45bcc4dc007a02b4ece698bbf73df205
```

S20L must preserve this byte digest while adding the separate v2 dataset.

## Frozen v2 Contract

The canonical contract is implemented by:

- `contracts/schemas/common/model_calibration_dataset.v2.schema.json`
- `nex_runtime.model_calibration_dataset`

The dataset identity is `s136-reranker-relevance-public-v2`. Admission
requires exactly 30 query groups and four labelled documents per query:

| Relevance grade | Document ID | Binary target |
| --- | --- | --- |
| `STRONG_POSITIVE` | `strong-positive` | true |
| `ACCEPTABLE_POSITIVE` | `acceptable-positive` | true |
| `HARD_NEGATIVE` | `hard-negative` | false |
| `EASY_NEGATIVE` | `easy-negative` | false |

The complete dataset therefore contains 120 pairs with a 60/60 positive and
negative balance.

The query-group quotas are frozen as follows:

```text
partition  = CALIBRATION 20 / HOLDOUT 10
language   = KOREAN 18 / KOREAN_ENGLISH_MIXED 6 / ENGLISH 6
domain     = PROJECT 6 / FINANCE 8 / IDENTITY_AUTHORIZATION 5 /
             GOVERNANCE_OPERATIONS 5 / AI_RUNTIME 6
```

Partitioning is performed only at query-group granularity. Case IDs are
lowercase kebab-case, document IDs are derived from relevance grade, and the
binary target must agree with that grade.

## Admission and Evidence Boundary

Admission rejects unknown fields, invalid quotas, duplicate case IDs,
duplicate normalized queries, duplicate normalized document text, incomplete
grade sets, and inconsistent grade/label/document-ID combinations.

The normalized dataset is ordered deterministically before hashing. Its
digest uses the existing `nex_runtime.semantic_hashes` canonical JSON SHA-256
implementation; no Slice-local hash helper was introduced.

The admitted result separates:

- the normalized dataset, which retains query and document text for provider
  execution; and
- a protected-evidence manifest containing only identity, digest, counts,
  quotas, and deterministic pair IDs.

This prevents S20M evidence from copying labelled text while preserving full
score lineage.

## Verification

```text
focused regression       = 56 passed
dataset contract tests   = 29 passed
contract validation      = PASS (228 schemas / 291 examples /
                           245 negative examples / 10 OpenAPI documents)
platform Slice Gate      = PASS
Slice Gate regression    = 456 passed / 8 protected skips
new module statement     = 100.00%
new module branch        = 100.00%
remote provider          = not required / not used
```

The first Gate invocation incorrectly applied the new-module `98/96` target
to the entire broad `nex-runtime` source scope. All 2,021 tests passed, but
that command was rejected by the coverage checker. The final platform Slice
Gate scoped coverage to the changed module and retained the requested
`98/96` thresholds; it passed at 100/100 without changing repository policy.

S20K is closed. S20L may now author and admit the v2 dataset against this
contract.
