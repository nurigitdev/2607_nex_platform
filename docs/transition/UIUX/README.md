# NeX AE Web UI/UX Modernization

This directory is the canonical transition documentation set for the NeX-AE
Web UI/UX modernization program.

## Reading Order

1. `NeX_AE_Web_UI_UX_Modernization_Source_Audit_and_Pre_Architecture_Decision_v1.0.md`
2. `UXM_CA01_Source_Backed_Entry_Baseline_and_Design_Asset_Admission_Closure_v1.0.md`
3. `tokens.json`
4. `tokens.css`
5. `NeX_AE_Web_UI_UX_Modernization_Implementation_Slice_Plan_v1.0.md`
6. `NeX_AE_Web_UIUX_Modernization_Final_AsBuilt_v1.0.md`

The PAD records the original architecture decision. UXM-CA01 is the mandatory
implementation-entry amendment and takes precedence where the original source
baseline, asset location, gate cadence, or Slice ordering differs.

## Current Status

```text
PAD                         = FROZEN
UXM-CA01                    = PASS / CLOSED
UXM-S01 through UXM-S04     = PASS / CLOSED
Foundation Checkpoint #1    = PASS / CLOSED
UXM-S05 through UXM-S07     = PASS / CLOSED
Security Boundary Checkpoint = PASS / CLOSED
UXM-S08 through UXM-S10     = PASS / CLOSED
Approval UX Checkpoint #2   = PASS / CLOSED
UXM-S11 through UXM-S19     = PASS / CLOSED
Full Web Acceptance #1      = PASS / CLOSED
UXM-S20 through UXM-S21     = PASS / CLOSED
Cutover/Retirement Checkpoint = PASS / CLOSED
UXM-S22                     = PASS / CLOSED
Repository Full Gate        = PASS / CLOSED
design token source         = PROMOTED / REPRODUCIBLE
UXM-S00                     = SATISFIED BY UXM-CA01
React production UI         = CANONICAL
legacy UI                   = RETIRED
PWA phase                   = NOT STARTED / SUCCESSOR
next implementation Slice   = NONE / PROGRAM CLOSED
implementation branch       = transition/ae-web-uiux-modernization
```

`tokens.json` is the canonical token source. `tokens.css` is its admitted,
reproducibly generated application projection; UXM-S03 closed generation and
validation drift before production promotion.

The Final As-Built is the canonical closure and handoff record. Protected
environment tests retain their explicit admission rules and are distinguished
from the deterministic Repository Full Gate evidence in that record.
