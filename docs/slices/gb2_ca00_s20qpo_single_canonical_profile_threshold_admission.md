# GB2-CA00-S20Q-P-O: Single Canonical Profile Threshold Admission

## Status

`CLOSED - CALIBRATION threshold candidate admitted; HOLDOUT required`

## Scope

P-O fits a threshold for the single P-L profile
`answer-support-contradiction-aware-v2`. It does not search profiles, change
weights, relax constraints, access Dataset v4 HOLDOUT, or activate a runtime
policy.

The input is the 200-package P-M fresh CALIBRATION extension evaluated under
the immutable P-N provider binding. No new provider or database calls occur in
this Slice.

## Protocol

Scenarios are grouped by `scenario_id` and assigned to five deterministic
outer folds using domain/language-stratified round robin. Every fold contains:

```text
training scenarios/packages   = 80 / 160
validation scenarios/packages = 20 / 40
validation domains            = 4 scenarios per domain
validation languages          = Korean 12 / mixed 4 / English 4
profile count                 = 1
```

Each fold fits its threshold from outer-training CALIBRATION only and applies
that frozen threshold to its validation partition. After OOF admission, the
candidate threshold is refit once on all 200 CALIBRATION packages.

## Admission Result

```text
candidate profile                    = answer-support-contradiction-aware-v2
candidate threshold                  = 0.46375
candidate status                     = CANDIDATE_NOT_ACTIVE
outer thresholds                     = 0.46375 in all five folds
threshold spread                     = 0.0
OOF package AUC                      = 1.0
OOF balanced accuracy                = 1.0
minimum outer balanced accuracy      = 1.0
OOF false-ready rate                 = 0.0
OOF READY recall                     = 1.0
false-ready 95% Wilson upper bound   = 0.0369935
READY recall 95% Wilson lower bound  = 0.9630065
```

All P-L point constraints passed. The threshold is a CALIBRATION candidate,
not a production-active threshold. The strong separation was measured on the
controlled synthetic P-M extension and therefore does not replace sealed
HOLDOUT generalization evidence.

## Integrity Binding

```text
P-M dataset              = sha256:dab6ef0d8ba09ea8b22fdd0f7a1f8bd937748c80e2a3f170c0caabfcbf44148b
P-N collection           = sha256:9ed7ed8c3a699d48c7090223749d60fe40574bae6e2520822cd0fc9d52749d4b
P-O design               = sha256:0f70676af6103b9053b0e568a1a96f11956227ac7e1cb7f7872bcd79eac9a9bc
P-O sample set           = sha256:c1e4768f46bcd1a23efb5ed4ac1a69596b97e9aa7d22824744f79a1af17f536d
P-O fold assignment      = sha256:feb375e264de98c63911e74b3dc23513b7e4d710598f64824fd99125473472c6
P-O calibration evidence = sha256:06016641346b9241ad20b0553490579512876891771e363eecca9b70f9604f0b
```

The machine-readable contract is
`scripts/smoke/data/s136_answer_support_canonical_calibration_v1_design.json`.
The ignored protected report is
`reports/live/gb2_ca00_s20qpo_canonical_threshold_admission.json`.

## Fail-Closed Boundaries

- A source dataset, collection, artifact, profile, or freeze hash mismatch is
  rejected before fitting.
- A missing outer-training threshold leaves the fold unevaluated and prevents
  candidate admission.
- OOF coverage, false-ready, recall, AUC, minimum fold accuracy, and threshold
  spread must all satisfy the frozen P-L constraints.
- A failed full-CALIBRATION refit revokes the candidate.
- Protected evidence remains text-free and contains no query, candidate, API
  key, or endpoint value.
- `runtime_activation_permitted=false` and HOLDOUT remains
  `SEALED_NOT_OPENED`.

## Verification

```text
focused product/runner tests          = 20 passed
new product statement/branch          = 100% / 100%
new protected runner statement/branch = 100% / 100%
protected P-O calibration              = PASS
NeX-CX Slice Gate direct/impact tests  = 209 passed
NeX-CX service regression              = 2,915 passed
repository statement coverage         = 99.12%
repository branch coverage            = 98.32%
contract validation                    = PASS
golden journey transition audit        = PASS
demo-to-product dependency audit       = PASS
```

The next acceptance boundary must explicitly decide whether to open the
sealed Dataset v4 HOLDOUT for one-shot evaluation. P-O itself authorizes
neither HOLDOUT access nor runtime activation.
