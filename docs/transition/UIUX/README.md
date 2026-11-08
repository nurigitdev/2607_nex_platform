# NeX AE Web UI/UX Modernization

This directory is the canonical transition documentation set for the NeX-AE
Web UI/UX modernization program.

## Reading Order

1. `NeX_AE_Web_UI_UX_Modernization_Source_Audit_and_Pre_Architecture_Decision_v1.0.md`
2. `UXM_CA01_Source_Backed_Entry_Baseline_and_Design_Asset_Admission_Closure_v1.0.md`
3. `tokens.json`
4. `tokens.css`
5. `NeX_AE_Web_UI_UX_Modernization_Implementation_Slice_Plan_v1.0.md`

The PAD records the original architecture decision. UXM-CA01 is the mandatory
implementation-entry amendment and takes precedence where the original source
baseline, asset location, gate cadence, or Slice ordering differs.

## Current Status

```text
PAD                         = FROZEN
UXM-CA01                    = PASS / CLOSED
UXM-S01 through UXM-S04     = PASS / CLOSED
Foundation Checkpoint #1    = PASS / CLOSED
design token source         = PROMOTED / REPRODUCIBLE
UXM-S00                     = SATISFIED BY UXM-CA01
next implementation Slice   = UXM-S05
implementation branch       = transition/ae-web-uiux-modernization
```

`tokens.json` is the canonical candidate source. `tokens.css` is the admitted
reference/generated candidate; UXM-S03 must prove reproducible generation and
validation before promoting either file into the application source tree.
