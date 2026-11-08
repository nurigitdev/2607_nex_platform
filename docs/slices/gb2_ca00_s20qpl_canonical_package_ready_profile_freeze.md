# GB2-CA00-S20Q-P-L: Canonical Package READY Semantics and Profile Design Freeze

## Status

`CLOSED - canonical profile frozen; fresh calibration required`

## Decision

The canonical package READY policy is
`answer-support-contradiction-aware-v2`. It preserves the exact feature
weights that were frozen before P-J while assigning a new product-policy
identity. No feature or weight was tuned after observing P-J or P-K.

The policy defines READY as sufficient answer support with bounded
contradiction. It includes direct/support coverage, second-candidate and
top-two support strength, maximum contradiction, and the normalized
support-to-contradiction margin. Missing features fail closed to NOT_READY.

`answer-support-top-two-v1` remains diagnostic history. It is not an equivalent
runtime alternative because P-K proved that its feature dependencies and
counterfactual behavior differ from the contradiction-aware profile.

## Boundary

P-L freezes product meaning and an exact score formula only. It does not:

- fit or select a threshold;
- reuse P-I/P-J evidence as admissible threshold evidence;
- open HOLDOUT;
- call a provider or database;
- activate a runtime policy;
- authorize an equivalence family or profile search.

The next evidence must contain 100 fresh CALIBRATION scenario pairs and 200
packages. Selection is restricted to a single canonical profile and threshold
calibration only.

## Integrity Binding

```text
P-K audit       = sha256:3f1df25d117b26e7a3d133d56960ccd04118f3a5ff5e881e262072893b0fcaa8
P-J selection   = sha256:3dad4bc80aad642d7628fe27ec5f06db4016143cfa66d1344f4b1c8332c4cc57
P-L design      = sha256:6547ab401826a8095882f693e40a1feb1e3a1efbc2c7daba0cbf84546491f197
canonical profile = sha256:495bbc63c50affddd70e90c97fc27655c94c5eeabf890a5f13f5c2df5f90a31e
freeze evidence = sha256:922d647c7ec37eef18dfa2c0384edd8411c52b491af324b1e8db4aaaef08ed9a
```

The machine-readable design is
`scripts/smoke/data/s136_answer_support_canonical_profile_v2_design.json`.
The ignored protected report is
`reports/live/gb2_ca00_s20qpl_canonical_profile_freeze.json`.

## Verification

```text
focused product/runner tests          = 15 passed
new product statement/branch          = 100% / 100%
new protected runner statement/branch = 100% / 100%
protected canonical freeze             = PASS
provider calls                         = 0
database calls                         = 0
NeX-CX Slice Gate                      = 2,881 passed
repository statement coverage         = 99.11%
repository branch coverage            = 98.29%
contract validation                    = PASS
golden journey transition audit        = PASS
demo-to-product dependency audit       = PASS
```

P-L closes the product-semantic decision without converting earlier
exploratory evidence into threshold evidence. P-M must now define and admit an
independent CALIBRATION-only extension while preserving the existing Dataset
v4 HOLDOUT unchanged and sealed.
