# GB2-CA00-S20Q-P-P: Pre-HOLDOUT Admission and One-Shot Execution Freeze

## Status

`CLOSED - one-shot HOLDOUT execution armed; not executed`

## Scope

P-P admits the P-O threshold candidate to one future blind Dataset v4 HOLDOUT
execution. It freezes the dataset, profile, threshold, provider revision,
request budget, receipt path, and failure disposition. It does not read
HOLDOUT values into calibration logic, call a provider, score a package, or
activate a runtime policy.

## Frozen Inputs

```text
Dataset                 = s136-retrieval-package-confidence-public-v4
Dataset file digest     = sha256:a0be13e113efee2a4a2dd904aaab6d65916a4e31b4a71b91465b66210d9dea20
Dataset semantic digest = sha256:594209203d25b0a87e6fd136b6794bdc30058a5eb45b7e2c8ff27523bd7f1757
HOLDOUT scenarios       = 20
HOLDOUT packages        = 40
HOLDOUT candidates      = 160
Profile                 = answer-support-contradiction-aware-v2
Profile hash            = sha256:495bbc63c50affddd70e90c97fc27655c94c5eeabf890a5f13f5c2df5f90a31e
Threshold               = 0.46375
Model revision          = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
```

Dataset v4 is admitted through its existing immutable checker. The freeze
contains only counts, digests, profile lineage, and execution controls. It
does not contain query text, candidate text, candidate truth, or HOLDOUT
labels.

## One-Shot Contract

```text
execution ID                  = s20qpq-4ba9f4f7633136589cda7d17
execution attempts            = 1
logical provider evaluations  = 40
maximum provider HTTP calls   = 40
maximum concurrency           = 4
provider request retry        = prohibited
profile change                = prohibited
threshold reselection         = prohibited
partial failure disposition   = TERMINAL_INCONCLUSIVE_CONSUMED
receipt path                  = reports/live/gb2_ca00_s20qpq_holdout_one_shot_receipt.json
```

P-Q must reserve the receipt as `STARTED` using
`ATOMIC_CREATE_EXCLUSIVE` before the first provider call. Any existing receipt
blocks a new freeze. `PASS`, `FAIL`, and `INCONCLUSIVE` are all terminal and
consume the authorization, so a crash or partial provider failure cannot
silently reopen the experiment.

## Integrity Binding

```text
P-O calibration = sha256:06016641346b9241ad20b0553490579512876891771e363eecca9b70f9604f0b
P-P design       = sha256:a944ca81d6c00768cd640102bd421c6447e17d1f0acb95b66498f71878096440
Authorization    = sha256:4ba9f4f7633136589cda7d17976afa3f2b1ce711c0e8dec67bd17e65527a1575
Freeze           = sha256:31236a3d8a7fa6f9e4834baa9eba4184374036414876710784028750ecc066e5
```

The machine-readable contract is
`scripts/smoke/data/s136_answer_support_holdout_one_shot_v1_design.json`.
The ignored protected report is
`reports/live/gb2_ca00_s20qpp_pre_holdout_freeze.json`.

## Fail-Closed Admission

The freeze is rejected when any of these conditions occurs:

- P-O calibration, profile, threshold, collection, artifact, or model revision
  differs from the frozen binding;
- OOF false-ready, recall, AUC, or P-O checks no longer satisfy admission;
- Dataset v4 file or semantic digest, counts, independent review, fold
  exclusion, or immutable status changes;
- a canonical receipt already exists;
- retries, a second execution, threshold relaxation, calibration re-entry, or
  runtime activation is requested.

## Verification

```text
focused product/runner tests          = 37 passed
new product statement/branch          = 100% / 100%
new protected runner statement/branch = 100% / 100%
protected P-P freeze                   = PASS
provider calls                         = 0
database calls                         = 0
HOLDOUT executions                     = 0
NeX-CX Slice Gate direct/impact tests  = 210 passed
NeX-CX service regression              = 2,947 passed
repository statement coverage         = 99.13%
repository branch coverage            = 98.32%
contract validation                    = PASS
golden journey transition audit        = PASS
demo-to-product dependency audit       = PASS
```

P-Q may execute only the frozen execution ID. It must create the reservation
receipt before provider access, preserve the fixed threshold and provider
binding, and publish one terminal receipt without authorizing runtime use.
