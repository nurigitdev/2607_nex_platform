# GB2-CA00-S20Q-C: Mixed-Candidate Package Semantics and Dataset v3 Contract Closure

## Outcome

S20Q-C closes the contract gap identified by S20Q-B without changing an
active runtime profile or weakening confidence constraints. Historical v1
and v2 datasets remain immutable. The v2 holdout is retained as regression
history but is not eligible as an untouched admission holdout after its result
was observed during S20Q-B.

S20Q-C introduces:

- `model_calibration_dataset.v3`;
- `s136-retrieval-package-confidence-public-v3`;
- scenario-paired READY and LOW_CONFIDENCE package cases;
- one complete mixed-candidate retrieval per package;
- deterministic package-level sample construction;
- fail-closed dataset and retrieval-scope admission.

No canonical v3 labelled text, dataset digest, remote-provider execution,
threshold, profile activation, or database migration is included in this
Slice.

## Why v2 Cannot Be Reused

The v2 collector issued two label-filtered retrievals for one query. The
positive retrieval contained only expected-ready documents and the negative
retrieval contained only expected-low-confidence documents. That construction
made reranker margin structurally inverted and made normalized RRF/channel
signals largely describe the artificial scope rather than production
confidence.

The production runtime does not know labels before retrieval. A calibration
package must therefore be built from the complete permitted candidate set in
one request.

## Dataset v3 Shape

The v3 contract contains 30 scenario families. Each scenario has exactly two
package cases with matching partition, language, and domain metadata:

```text
<scenario>-ready
<scenario>-low-confidence
```

Composition:

```text
scenario families                = 30
package cases                    = 60
candidates                       = 240
CALIBRATION scenarios/packages   = 20 / 40
HOLDOUT scenarios/packages       = 10 / 20
READY packages                   = 30
LOW_CONFIDENCE packages          = 30
```

The scenario quotas remain aligned with the reviewed v2 business corpus:

```text
language = KOREAN 18 / KOREAN_ENGLISH_MIXED 6 / ENGLISH 6
domain   = PROJECT 6 / FINANCE 8 / IDENTITY_AUTHORIZATION 5 /
           GOVERNANCE_OPERATIONS 5 / AI_RUNTIME 6
```

READY and LOW_CONFIDENCE cases from one scenario may never be split across
calibration and holdout. Query text and candidate text must be globally unique
after whitespace/case normalization.

## Package Labels and Candidate Roles

A READY package has one complete retrieval over:

1. `PRIMARY_ANSWER`;
2. `SUPPORTING_ANSWER`;
3. `HARD_NON_ANSWER`;
4. `EASY_NON_ANSWER`.

A LOW_CONFIDENCE package has one complete retrieval over:

1. `HARD_NON_ANSWER`;
2. `RELATED_NON_ANSWER`;
3. `CONTRADICTORY_NON_ANSWER`;
4. `EASY_NON_ANSWER`.

The package label is not inferred from a top-ranked candidate after execution.
It is frozen source truth. Candidate roles provide ranking diagnostics but do
not permit candidate filtering before feature extraction.

## Runtime Collection Boundary

`build_mixed_candidate_calibration_sample()` requires:

- all four admitted candidate IDs exactly once;
- ranks `1..4` exactly once;
- one feature package built from all four numeric evidence items;
- no query text, document text, permission signal, or ownership signal in the
  calibration evidence;
- sample identity `<scenario>:positive|negative` for group-aware CV;
- `single_mixed_candidate_retrieval=true` and
  `label_filtered_retrieval=false`.

The existing multi-signal package integrity and model/policy binding remain in
force. S20Q-C does not declare the existing four features discriminative; it
only corrects the unit of observation so later live evidence can evaluate
them honestly.

## Admission and Evidence

The v3 admission layer rejects:

- missing, duplicate, or malformed scenario pairs;
- cross-partition or metadata-drifting pairs;
- label/role mismatch;
- candidate ID/role/relevance mismatch;
- duplicate normalized query or candidate text;
- quota drift and unknown fields.

The manifest contains only identities, semantic digest, counts, quotas, and
public case/candidate IDs. Raw labelled text is excluded. Canonical hashing
uses `nex_runtime.semantic_hashes`; no Slice-local digest implementation was
added.

## Frozen Safety Boundary

The following remain unchanged:

```text
maximum false-ready rate = 0.10
minimum ready recall     = 0.80
group-aware folds        = required
holdout threshold tuning = prohibited
runtime activation       = fail closed
```

No sign inversion or special handling is hard-coded for the current Qwen
model. Future model revisions must be admitted against their own immutable
binding and live evidence.

## Verification

Focused contract and package-semantics regression:

```text
49 passed
v3 admission module statement/branch = 99% / 98%+
mixed-package module statement/branch = 100% / 100%
```

NeX-CX Slice Gate:

```text
regression tests = 2,625 passed
statement coverage = 99.01% (minimum 95.00%)
branch coverage = 98.23% (minimum 94.00%)
contract validation = 229 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = pass
demo-to-product dependency audit = pass
```

The broad Gate used the canonical NeX-CX service coverage source. The shared
v3 admission module was measured in the focused run because adding that single
module as a second `pytest-cov` source causes coverage discovery to interfere
with `openapi-spec-validator` package-schema loading. The failure was
reproduced with the OpenAPI test alone and the module-level coverage source;
the same test passes both without that source and under the canonical service
coverage source. Product and contract behavior were therefore not bypassed.

## Handoff

The next corrective Slice should be:

`S20Q-D: Dataset v3 Authoring, Admission, and Immutable Digest Freeze`

It must author 30 reviewed scenario pairs without mechanical paraphrase,
freeze the canonical digest, and preserve v1/v2 byte and semantic identities.
Live provider execution begins only after that authoring/admission Slice.
