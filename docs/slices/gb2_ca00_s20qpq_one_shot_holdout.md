# GB2-CA00-S20Q-P-Q: One-Shot HOLDOUT Execution

## Status

`CLOSED - HOLDOUT admitted; authorization consumed; runtime still disabled`

## Scope

P-Q executed the P-P authorization exactly once against the immutable Dataset
v4 HOLDOUT partition. It used the frozen canonical profile, threshold,
generation artifact revision, concurrency, and request budget. It did not fit
or reselect a threshold, compare profiles, retry a provider request, access a
database, or activate a runtime policy.

## Frozen Execution

```text
execution ID          = s20qpq-4ba9f4f7633136589cda7d17
authorization hash    = sha256:4ba9f4f7633136589cda7d17976afa3f2b1ce711c0e8dec67bd17e65527a1575
profile               = answer-support-contradiction-aware-v2
profile hash          = sha256:495bbc63c50affddd70e90c97fc27655c94c5eeabf890a5f13f5c2df5f90a31e
threshold             = 0.46375
provider revision     = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
deployment            = dgx-qwen3-5-9b-9116
HOLDOUT scenarios     = 20
HOLDOUT packages      = 40
HOLDOUT candidates    = 160
maximum concurrency   = 4
provider retries      = 0
```

The runner reconstructed the P-P freeze from the immutable P-O calibration,
Dataset v4 checker, and P-P design before creating the receipt. Any source,
profile, threshold, dataset, provider binding, or execution-ID drift fails
before provider access.

## One-Shot Safety

The canonical receipt was created with `O_CREAT | O_EXCL`, mode `0600`, and
`fsync` before the first provider request. Terminal replacement uses a
same-directory temporary file, `fsync`, and atomic `os.replace`.

```text
receipt path   = reports/live/gb2_ca00_s20qpq_holdout_one_shot_receipt.json
receipt status = PASS
attempt number = 1
started at     = 2026-11-05T00:30:17.512033Z
completed at   = 2026-11-05T00:33:16.475336Z
receipt hash   = sha256:1bbfa3983dcad9b0aa39ace9be8eca57dfbd4a7bc1484b2f01366c8ccf5caa68
```

PASS, FAIL, and INCONCLUSIVE all consume the authorization. A provider error,
partial collection, process interruption after reservation, malformed output,
or budget violation cannot reopen the experiment. An existing receipt blocks
all subsequent execution before a provider call.

## Live HOLDOUT Result

```text
provider evaluations = 40
provider HTTP calls   = 40
true READY            = 20
false low-confidence  = 0
false READY           = 1
true low-confidence   = 19
false-ready rate      = 0.05   (required <= 0.10)
READY recall          = 1.00   (required >= 0.80)
balanced accuracy     = 0.975
package AUC           = 1.00   (required >= 0.80)
```

All three frozen point constraints passed. The Wilson 95% interval is
`[0.00888145, 0.23613119]` for false-ready rate and
`[0.83887484, 1.0]` for READY recall. Point constraints remain authoritative,
as frozen by P-P.

Provider classifications across the 160 candidates were:

```text
CONTRADICTORY_EVIDENCE = 17
DIRECT_ANSWER          = 20
INSUFFICIENT_CONTEXT   =  3
SUPPORTING_EVIDENCE    = 22
TOPICAL_NON_ANSWER     = 98
```

## Integrity and Privacy

```text
collection hash = sha256:c99f7d676cbe720b9cb9371bc7bfdc3056ef36b0282d63dd8b6297e5772d14be
evaluation hash = sha256:e3696095c0fb198ce35d65b291e3121d8a099e6a4fafb993d28be265f3c9a28c
```

Protected evidence stores hashes, normalized classifications, bounded scores,
provider lineage, aggregate metrics, and the consumed receipt. It excludes raw
query text, candidate text, provider output text, endpoints, credentials, and
candidate truth. Truth labels are joined only after all provider observations
are collected and are never provider inputs.

The ignored local evidence files are:

- `reports/live/gb2_ca00_s20qpq_one_shot_holdout.json`
- `reports/live/gb2_ca00_s20qpq_holdout_one_shot_receipt.json`

## Decision

```text
HOLDOUT decision        = HOLDOUT_ADMITTED
authorization           = CONSUMED
threshold reselection   = prohibited / not performed
profile reselection     = prohibited / not performed
runtime activation      = prohibited
next boundary           = separate activation/readiness decision
```

Passing P-Q proves the frozen candidate on the untouched HOLDOUT. It does not
activate the profile by itself. Runtime adoption requires a separate Slice
that binds this receipt and evaluation to an explicit operational policy and
rollback boundary.

## Verification

```text
focused product/runner tests          = 20 passed
new product statement/branch          = 100% / 100%
new protected runner statement/branch = 100% / 100%
actual provider HOLDOUT                = PASS
provider evaluations / HTTP requests  = 40 / 40
receipt mode / terminal status        = 0600 / PASS
NeX-CX service regression              = 2,962 passed
repository statement coverage         = 99.14%
repository branch coverage            = 98.35%
contract validation                    = PASS (230 schemas, 291 examples,
                                         245 negative examples, 10 OpenAPI)
golden journey transition audit        = PASS
demo-to-product dependency audit       = PASS
```
