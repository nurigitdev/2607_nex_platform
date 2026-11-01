# GB2-CA00-S20L 120-Sample Dataset Authoring and Admission

## Status

`CLOSED`

## Scope

S20L authors and freezes the v2 reranker calibration dataset admitted by the
S20K contract. It does not call a remote provider and does not select a
confidence threshold.

## Dataset

The canonical source is:

```text
path       = scripts/smoke/data/s136_reranker_calibration_v2.json
dataset id = s136-reranker-relevance-public-v2
sha256     = a59c47a2401004897ab5f03cd911f76aee09e81d3df9c59d799b553175665899
```

The SHA-256 is the semantic digest of the normalized dataset. Both case order
and document order are canonicalized by the S20K admission layer before the
digest is calculated.

Composition:

```text
query groups       = 30
labelled pairs     = 120
positive / negative = 60 / 60
calibration / holdout query groups = 20 / 10
Korean / mixed / English query groups = 18 / 6 / 6
project / finance / identity / governance / AI query groups = 6 / 8 / 5 / 5 / 6
```

Each query contains one strong positive, one acceptable positive, one hard
negative, and one easy negative. Hard negatives use confusable business
semantics such as create versus update, request versus approval, current
authority versus stale session, identical idempotency key with conflicting
payload, and retrieval versus reranking. General-knowledge text is used only
as an easy-negative control.

No query group is split between calibration and holdout. Admission also proves
that normalized query text and document text are unique across the complete
dataset.

## Immutable Admission

`scripts/quality/check_model_calibration_dataset.py` provides the source-backed
admission command. It verifies both frozen identities before returning the
redacted v2 manifest:

```text
v1 file sha256 = 743bee364a8f576b857380d3e6f0dffb45bcc4dc007a02b4ece698bbf73df205
v2 semantic sha256 = a59c47a2401004897ab5f03cd911f76aee09e81d3df9c59d799b553175665899
```

The v1 file was not modified. A structurally valid v2 file with changed text
is rejected because its semantic digest no longer matches the S20L baseline.
The command uses the shared `nex_runtime.semantic_hashes` implementation and
does not introduce another SHA-256 helper.

## Verification

```text
dataset admission command = PASS
focused regression        = 32 passed
platform Slice Gate       = PASS
Slice Gate regression     = 459 passed / 8 protected skips
changed modules statement = 100.00%
changed modules branch    = 100.00%
contract validation       = PASS (228 schemas / 291 examples /
                            245 negative examples / 10 OpenAPI documents)
remote provider           = not required / not used
```

The protected skips are unrelated PostgreSQL topology, trust, and restart
acceptances and are not counted as S20L evidence.

S20L is closed. S20M may execute this exact dataset twice against the admitted
reranker and bind live scores to the frozen v2 digest.
