# GB2-CA00-S20Q-P-M: Fresh CALIBRATION Extension Contract and Immutable Admission

## Status

`CLOSED - fresh CALIBRATION extension admitted; provider collection required`

## Scope

P-M defines and admits a deterministic CALIBRATION-only extension for the
single P-L canonical profile. It contains 100 new scenario pairs, 200 packages,
and 800 candidates. It does not mutate Dataset v4 or contain HOLDOUT content.

The extension is a controlled synthetic policy-fact matrix. It is not
represented as independently human-reviewed production data. Its review
boundary is the contract and deterministic generator, while the unchanged
sealed Dataset v4 HOLDOUT remains the authority for generalization.

## Dataset Contract

```text
scenarios                         = 100
READY / LOW packages per scenario = 1 / 1
packages                          = 200
candidates per package            = 4
candidates                        = 800
partition                         = CALIBRATION only
HOLDOUT cases                     = 0
```

Language quotas are Korean `60`, Korean/English mixed `20`, and English `20`.
The five domains each contain 20 scenarios:

- `PROJECT`
- `FINANCE`
- `IDENTITY_AUTHORIZATION`
- `GOVERNANCE_OPERATIONS`
- `AI_RUNTIME`

Every READY package contains primary and supporting answers plus hard and easy
non-answers. Every LOW_CONFIDENCE package contains hard, related,
contradictory, and easy non-answers. Query and candidate text are unique and
have no normalized overlap with Dataset v4.

## Implementation

`nex_cx.retrieval_answer_support_fresh_calibration` validates the design,
binds it to the intact P-L freeze, deterministically materializes the scenario
matrix, verifies quotas and package pairing, rejects predecessor overlap, and
emits an immutable semantic dataset hash.

The machine-readable contract is
`scripts/smoke/data/s136_answer_support_fresh_calibration_v1_design.json`.
The dataset is reconstructed from the versioned generator rather than stored
as a duplicated large JSON file. The design, generator ID, source hashes, and
resulting dataset hash fully bind the materialization.

## Integrity Binding

```text
P-L design       = sha256:6547ab401826a8095882f693e40a1feb1e3a1efbc2c7daba0cbf84546491f197
P-L profile      = sha256:495bbc63c50affddd70e90c97fc27655c94c5eeabf890a5f13f5c2df5f90a31e
P-L freeze       = sha256:922d647c7ec37eef18dfa2c0384edd8411c52b491af324b1e8db4aaaef08ed9a
P-M design       = sha256:764d1c5855e37e1c1a8d3c1c6ca597f08f35bc74434b26d9f341aec70e695241
P-M dataset      = sha256:dab6ef0d8ba09ea8b22fdd0f7a1f8bd937748c80e2a3f170c0caabfcbf44148b
```

The ignored protected report is
`reports/live/gb2_ca00_s20qpm_fresh_calibration_admission.json`.

## Verification

```text
focused product/runner tests          = 18 passed
new product statement/branch          = 100% / 100%
new protected runner statement/branch = 100% / 100%
protected immutable admission          = PASS
provider calls                         = 0
database calls                         = 0
NeX-CX Slice Gate                      = 2,896 passed
repository statement coverage         = 99.12%
repository branch coverage            = 98.30%
contract validation                    = PASS
golden journey transition audit        = PASS
demo-to-product dependency audit       = PASS
```

P-M does not select a threshold or establish production generalization. P-N
must collect provider-backed answer-support evidence for all 200 packages
under one immutable generation revision and the existing reasoning-disabled
request profile. HOLDOUT remains sealed.
