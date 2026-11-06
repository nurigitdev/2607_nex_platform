# GB2-CA00-S20Q: Multi-Signal Live Holdout Acceptance Closure

## Outcome

Status: `PASS`

Decision:

`MULTI_SIGNAL_LIVE_HOLDOUT_ACCEPTANCE_CLOSED`

The original S20Q acceptance boundary is closed from the exact P-A live
retrieval evidence, P-Q one-shot HOLDOUT evidence and receipt, P-AS corrective
operations closure, and P-AT controlled maintenance baseline.

This closure does not rerun HOLDOUT, call a provider or database, change the
runtime, reselect a profile or threshold, or authorize production cutover. It
is a pure integrity and semantic reconciliation boundary over already produced
evidence.

## Scope Reconciliation

The original S20Q scope required:

1. Permission-filtered hybrid retrieval package execution.
2. Actual CX PostgreSQL, embedding, and reranking evidence.
3. Immutable tokenizer, chunk, ranking, and model-revision binding.
4. Evaluation of a frozen policy on untouched HOLDOUT.
5. Protected acceptance evidence and Checkpoint Gate.

The corrective chain admitted one controlled extension: provider-backed
answer-support and contradiction signals. The extension was governed by
separate calibration, a single authorized HOLDOUT execution, and staged
runtime adoption. It did not replace or weaken the original retrieval
contract.

`GB2-CA00-S20Q-P-C` was an intermediate `FAIL / NO_ADMISSIBLE_PROFILE`
calibration result and is deliberately not used as acceptance evidence.

## Frozen Source Lineage

```text
closure design       = sha256:de349cf242997046aca75d7e10c83a519f9383d115035b8f4be84bd0b7bfd0df
P-A report document  = sha256:0d751565b83161867eeddcc4644e4d80e88dfb2464891724591287128213ea00
P-Q report document  = sha256:2fe99617c64d25d2c500f065e2c53db38069a8696f37588feaf44c78e9cbe998
P-Q receipt document = sha256:003ecfe1800021c1b88c64bd15ed6b722ecd953d4d0b0dc930162b386433fb25
P-Q receipt          = sha256:1bbfa3983dcad9b0aa39ace9be8eca57dfbd4a7bc1484b2f01366c8ccf5caa68
P-Q evaluation       = sha256:e3696095c0fb198ce35d65b291e3121d8a099e6a4fafb993d28be265f3c9a28c
P-AS report document = sha256:9b192a2c333729efd35e6b9339e5e7771281b5bc828f3de7c3d4062068235fa0
P-AS closure         = sha256:85409ddcb64b30381366fd2e38386529908c51968a5f91eca060174e1288047b
P-AT report document = sha256:6ffeaef8f14ad2ae658275e27af3c8ba8279f214a534bdf75a45c1a9c9fb41ef
P-AT maintenance     = sha256:e1a09694fb93b8b3d955bb7fb9e7ad6ebc949aeb3938e120e418fb64390b42ce
selected policy      = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
```

All source reports committed for this closure are redacted evidence documents.
They contain no endpoint, API key, database credential, raw query, raw
candidate text, or provider output text.

## Acceptance Facts

P-A proves the actual retrieval boundary:

```text
database / role       = nex_cx_test / nex_cx_user
CALIBRATION scenarios = 80
packages / candidates = 160 / 640
embedding calls       = 1,440 successful, 0 failed
reranking calls       = 800 successful, 0 failed
embedding revision    = hf:5cf2132abc99cad020ac570b19d031efec650f2b
reranker revision     = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
chunk policy          = chunk_1000_100
ranking policy        = weighted_rrf_vector_bm25_v1
pipeline repeatability= STABLE
```

P-Q proves the one-shot HOLDOUT boundary:

```text
HOLDOUT scenarios     = 20
packages / candidates = 40 / 160
profile               = answer-support-contradiction-aware-v2
threshold             = 0.46375
provider evaluations  = 40
provider HTTP calls   = 40
false-ready rate      = 0.05
ready recall          = 1.0
balanced accuracy     = 0.975
package AUC           = 1.0
authorization attempt = 1, terminal PASS
```

P-AS and P-AT prove that the corrective chain is closed, the baseline is
frozen, maintenance remains active without drift or overdue review, rollback
is preserved, and no new corrective chain is open.

## Implementation

- Frozen closure design:
  `scripts/smoke/data/s136_multi_signal_live_holdout_acceptance_closure_v1_design.json`
- CX integrity and semantic evaluator:
  `services/nex-cx/nex_cx/retrieval_multisignal_holdout_acceptance_closure.py`
- Protected evidence runner:
  `scripts/smoke/run_gb2_s20q_multi_signal_live_holdout_acceptance_closure.py`
- Owner-private closure evidence:
  `reports/live/gb2_ca00_s20q_multi_signal_live_holdout_acceptance_closure.json`

No migration, API route, runtime wiring, Compose setting, provider request,
database access, or HOLDOUT access was added.

## Protected Closure Evidence

All 22 closure checks passed:

```text
closure status        = CLOSED_PASS
corrective chain      = CLOSED
provider calls        = 0
database calls        = 0
HOLDOUT accessed      = false
HOLDOUT reexecution   = prohibited
profile reselection   = prohibited
runtime changed       = false
production cutover    = false
closure hash          = sha256:5a2cb9c019d78e55c12288903764b0421d69100a68f04788c82bb5fd7095f4e0
```

The closure evidence is mode `0600`. Its file SHA-256 is:

`47ad1cf68d789acba9b6b3fc7b157427b99eff15489a92edf15d7c7e1ce1aac7`

## Verification

```text
focused tests             = 23 passed
focused statement/branch  = 100% / 100%
S20Q regression            = 337 passed
protected closure          = PASS

Repository Checkpoint Gate = 19,586 passed, 132 skipped
statement coverage         = 98.67%
branch coverage            = 97.33%
contract validation        = 230 schemas, 291 examples,
                             245 negative examples, 10 OpenAPI documents
golden transition audit    = PASS, 9 registered, 1 enforced
dependency audit           = PASS, 742 product files, 7/7 edges
tiered Checkpoint Gate      = 5/5 commands passed
```

## Next Boundary

`GB2-CA00-S20R: Calibration Closure and Deferred Live Matrix Replay`

S20R must consume this closure as immutable input. It may replay only the
separately deferred live matrix defined by S20R; it must not reopen or rerun
the consumed S20Q one-shot HOLDOUT.
