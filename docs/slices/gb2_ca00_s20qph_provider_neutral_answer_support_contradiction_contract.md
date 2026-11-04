# GB2-CA00-S20Q-P-H: Provider-Neutral Answer-Support/Contradiction Signal Contract

## Status

Complete. The provider-neutral contract required by P-G is frozen without
selecting a provider, opening HOLDOUT, choosing a threshold, or activating a
runtime policy.

## Boundary

P-H defines the shape and safety semantics of a future answer-support signal.
It does not prove that a model can produce an admissible signal. Live provider
collection, calibration, nested profile selection, and HOLDOUT acceptance
remain later work.

The contract enforces the following boundaries:

- authorization and owner-scope filtering happen before provider evaluation;
- query and candidate text are private, ephemeral request inputs;
- persisted evidence contains hashes, candidate IDs, classes, scores, and an
  exact provider binding, but no source text or free-form rationale;
- candidate truth, permission state, and ownership state are not features;
- scores are bounded ordinal signals, not calibrated probabilities;
- no READY threshold or READY decision is emitted.

## Signal Contract

The frozen classes are:

```text
DIRECT_ANSWER
SUPPORTING_EVIDENCE
TOPICAL_NON_ANSWER
CONTRADICTORY_EVIDENCE
INSUFFICIENT_CONTEXT
```

Every candidate receives `answer_support_score` and `contradiction_score` in
`[0, 1]`. `DIRECT_ANSWER` and `SUPPORTING_EVIDENCE` require support to exceed
contradiction. `CONTRADICTORY_EVIDENCE` requires the inverse. These checks only
validate the provider assertion's internal consistency; they do not establish
ground truth.

The exact provider binding is:

```text
provider_alias
provider_type
model_revision
deployment_id
request_profile_id
score_semantics_id
```

No field fixes the implementation to a particular vendor, transport, model
family, or model size. A response whose binding differs from the admitted
request context fails closed.

## Privacy And Integrity

The request carries raw text only because an evaluator must inspect the query
and candidate relationship. The normalized evidence replaces that text with
SHA-256 digests and is protected by a semantic evidence hash. The package
projection verifies the evidence hash again before producing features.

Strict field sets reject hidden rationale, candidate truth, endpoint, API key,
or arbitrary provider metadata. Rehashing a structurally invalid request or
evidence object does not make it admissible; semantic validation runs after
integrity validation.

## Package Projection

P-H exposes diagnostic features for a later calibration Slice:

```text
direct_or_support_fraction
second_answer_support_score
top_two_answer_support_mean
maximum_contradiction_score
mean_contradiction_score
support_contradiction_margin
```

The projection contains class counts and the exact provider binding. It does
not select a profile, threshold, or runtime action.

## Implementation

- `nex_cx.retrieval_answer_support_signal` implements design validation,
  private request construction, response normalization, integrity validation,
  and diagnostic package projection.
- `s136_answer_support_signal_v1_design.json` is the machine-readable frozen
  contract.
- `run_gb2_s20qph_answer_support_signal_contract.py` executes an offline,
  protected contract probe and verifies that persisted projections contain no
  forbidden raw-text keys.

No database schema, public API, active retrieval policy, or provider route was
changed.

## Verification

```text
focused regression = 31 passed
new product module statement coverage = 100%
new product module branch coverage = 100%
focused contract and runner coverage = 99%
protected contract smoke = PASS
provider calls = 0
database calls = 0
holdout calls = 0
runtime activation = prohibited
NeX-CX Slice Gate = 2,805 passed
repository statement coverage = 99.07%
repository branch coverage = 98.20%
contract validation = PASS
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

P-H closes the contract gap identified by P-G. It does not unblock S20Q
HOLDOUT. The next corrective boundary must design and execute CALIBRATION-only
provider collection against this contract before any nested admission or
HOLDOUT decision.
