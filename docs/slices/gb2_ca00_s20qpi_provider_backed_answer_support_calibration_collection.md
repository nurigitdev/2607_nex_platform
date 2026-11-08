# GB2-CA00-S20Q-P-I: Provider-backed Answer-Support CALIBRATION Collection

## Status

`CLOSED - CALIBRATION evidence collected; P-J admission still required`

## Scope

This Slice connects the provider-neutral answer-support and contradiction
contract frozen by P-H to an admitted live generation provider. It collects
signals for Dataset v4 `CALIBRATION` cases only. It does not select a profile,
freeze a threshold, inspect HOLDOUT, emit a READY decision, or activate a
runtime retrieval policy.

## Implementation

- `retrieval_answer_support_collection.py` validates the frozen generation
  request profile, builds private provider requests, normalizes provider JSON
  into P-H text-free evidence, and creates an integrity-bound collection.
- `s136_answer_support_generation_profile_v1.json` freezes JSON response mode,
  disabled reasoning, temperature `0`, ordinal score semantics, and the
  untrusted-candidate safety instruction.
- The protected runner admits Dataset v4 and P-C-A retrieval evidence, verifies
  immutable model artifact evidence, blocks all HOLDOUT query and candidate
  content at the HTTP boundary, and rejects any persisted raw text or protected
  provider configuration.
- Provider calls use bounded concurrency `4`, matching the installed vLLM
  `max-num-seq` limit. Case admission, duplicate detection, evidence merge,
  provider-binding validation, deterministic package sorting, and collection
  hashing remain serialized.
- No database schema, public API, active runtime policy, or production threshold
  changed.

## Live Provider Binding

The previously documented `9111/Qwen3.5-4B` route was not active during this
Slice. The live collection used the currently installed generation route on
port `9116` with served model `Qwen3.5-9B`.

```text
provider type       = vllm
provider alias      = general-llm-default
deployment id       = dgx-qwen3-5-9b-9116
artifact revision   = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
request profile     = s136-answer-support-generation-json-v1
score semantics     = bounded-ordinal-answer-support-v1
reasoning mode      = disabled
temperature         = 0
```

The revision was extracted from the local model artifact by the model-owning
DGX account. The protected evidence stores neither the model path nor artifact
content.

## Live Collection Evidence

The ignored local report is
`reports/live/gb2_ca00_s20qpi_answer_support_calibration_collection.json`.

```text
status                       = PASS
CALIBRATION packages         = 160
candidate observations       = 640
provider evaluations         = 160
provider HTTP requests       = 160
maximum provider concurrency = 4
provider length/error exits  = 0/0
HOLDOUT provider requests    = 0
database calls in P-I        = 0
source database identity     = nex_cx_test / nex_cx_user
runtime activation           = disabled
collection hash              = sha256:2ef316848a3c3f503856de53e52c80ff9ec94162e59afee966504cb1f8ef530a
```

The 640 candidate classifications were:

```text
DIRECT_ANSWER          = 81
SUPPORTING_EVIDENCE    = 93
TOPICAL_NON_ANSWER     = 371
CONTRADICTORY_EVIDENCE = 80
INSUFFICIENT_CONTEXT   = 15
```

These counts are observations, not an acceptance decision. Scores remain
bounded ordinal signals and must not be interpreted as calibrated
probabilities.

## Safety Closure

- Only the 160 `CALIBRATION` cases reached the provider.
- All 40 `HOLDOUT` cases remained sealed and their query/candidate values were
  installed as forbidden HTTP-request content.
- `expected_ready`, `expected_relevant`, and `evidence_role` were not supplied
  to the provider and were not persisted in collection evidence.
- Raw query text, candidate text, provider output text, endpoints, and API keys
  are absent from the report.
- Every candidate retains only its stable identifier, classification, scores,
  and SHA-256 text digest.
- Provider artifact revision and deployment binding are identical across all
  packages.

## Verification

```text
focused regression                       = 25 passed
new product module statement coverage    = 100%
new product module branch coverage       = 100%
focused product/runner combined coverage = 99%
protected live collection                = PASS
NeX-CX Slice Gate                        = 2,830 passed
repository statement coverage            = 99.09%
repository branch coverage               = 98.20%
contract validation                      = PASS
golden journey transition audit          = PASS
demo-to-product dependency audit         = PASS
```

P-I provides the immutable CALIBRATION collection required by P-J. P-J must
re-run nested package calibration against this collection and make a separate
fail-closed admission decision before any HOLDOUT access or runtime activation.
