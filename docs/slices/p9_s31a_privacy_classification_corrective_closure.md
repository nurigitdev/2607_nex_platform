# P9-S31A: Privacy Classification Corrective Closure

## Scope

P9-S31A corrects one bounded privacy-contract mismatch discovered after the
P9-S31 freeze. AgentResult PRIMARY evidence, its Agent WorkAsset, and the WC
WorkResult SUPPORTING evidence now default to `CONFIDENTIAL` when their
authoritative source projection has no compatible classification.

This Slice does not change the P9 architecture, source authority, identity,
completion barrier, PRIMARY/SUPPORTING cardinality, API, database schema,
deployment topology, queue model, or authorization model.

## Implementation

```text
services/nex-wa/nex_wa/agent_result_source.py
  DEFAULT_AGENT_WORK_CLASSIFICATION = CONFIDENTIAL

AE_AGENT_RESULT PRIMARY WorkEvidence       -> CONFIDENTIAL
AGENT_EXECUTION_RESULT WorkAsset           -> CONFIDENTIAL
WC_WORK_RESULT SUPPORTING WorkEvidence     -> CONFIDENTIAL
AE_ARTIFACT INTERNAL                       -> CONFIDENTIAL
AE_ARTIFACT CONFIDENTIAL                   -> CONFIDENTIAL
AE_ARTIFACT RESTRICTED                     -> RESTRICTED
```

Regression coverage proves that deterministic WorkEvidence and WorkAsset IDs
do not change, while the classification-sensitive semantic hashes change
deterministically and remain stable on exact replay.

## Corrected Executable Baseline

```text
commit         = a4ef2f76d2b34e937f8e30316743302126c435ed
tree           = 1a16ed5dbabfa9060bdbb045845bbc1c665d500c
contracts tree = 9fdf95175cbcaf22c13fca81009ccd26c69578e9
```

## Verification

```text
focused S17/S18/S19/S20 regression = 68 passed, 1 protected skip
protected PostgreSQL acceptance    = 41 passed
NeX-WA Slice Gate                   = 319 passed, 12 protected skips
Slice statement / branch           = 97.31% / 94.70%
Repository Full Gate               = 18,268 passed, 131 protected skips
Full statement / branch            = 96.01% / 95.22%
contract validation                = 226 / 290 / 244 / 10
AE Web Node regression             = PASS
git diff --check                   = PASS
```

The protected run used actual `nex_ae_test`, `nex_wc_test`, `nex_oa_test`,
`nex_eos_test`, and `nex_wa_test` PostgreSQL databases with signed service
trust. Persisted classification assertions covered AgentResult PRIMARY,
Agent WorkAsset, WC SUPPORTING, and Human Artifact rows.

## Evidence Identities

```text
protected acceptance JUnit sha256 = e7a966ab335bf145ae279fe58715b2fe58d488d5e436681d1f772787062e6551
NeX-WA Slice coverage sha256       = 12cbe97d8784bf39fbbfb53e076743fe2d238959331504016cff5dfd29760205
Full Gate coverage JSON sha256     = 0e4f3a47a127b5e0d701b5ca5f0bab6c2604f33ca1853aa45fe724dcd4a3746e
Full Gate JUnit sha256             = 9254daa340a78eafc8283578fc886b94ceff78e7f774ae1564634b4fc0973795
```

The reports are local ignored artifacts. Their hashes bind this record to the
accepted runs without committing environment-specific output.

## Historical Data and Residue

The local `nex_wa_test` pre-check found no retained affected evidence, and
`nex_wa_dev` has no WA schema. No staging or production environment was in
scope, so no historical row rewrite was attempted or authorized.

After protected acceptance, the owned tenant residue was:

```text
nex_wa_test  = 0
nex_ae_test  = 0
nex_wc_test  = 0
nex_oa_test  = 0
nex_eos_test = 0
```

## Exit

```text
P9-S31A             = COMPLETE
privacy conformance = CORRECTED
runtime schema/API  = UNCHANGED
P9 Foundation       = CLOSED / REVALIDATED
P9.5                = DEFERRED
next phase          = CONTROLLED DECISION REQUIRED
```
