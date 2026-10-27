# P9-S31: Final As-Built and Handoff Freeze

## Scope

P9-S31 freezes the accepted P9-S30 executable baseline without changing
runtime behavior, public contracts, or database schemas. The authoritative
record is:

```text
docs/transition/P9/P9_Final_AsBuilt_Baseline_and_Next_Phase_Handoff_v1.0.md
```

The P9 README now points to that final record and marks P9 Foundation closed.
The Compose README was reconciled with the S27 source-backed topology: the WA
evidence consumer is an active installed work-claiming daemon, not the earlier
S25 readiness-only placeholder.

## Frozen Baseline

```text
executable commit = bc28307a58b659c791211d995ea773c77ef786c0
executable tree   = 0b687578bb120e68b67f0f14bb5cab9f376496cf
contracts tree   = 9fdf95175cbcaf22c13fca81009ccd26c69578e9
artifacts/processes = 9 / 17
source/applied migrations = 171 / 171
P9.5 = DEFERRED
```

## Revalidation

- actual eight-service test DB identity and migration-head comparison: `PASS`
- actual WA image identity and non-root user comparison: `PASS`
- protected AE/WC/OA/EOS/WA acceptance rerun: `41 passed`
- post-rerun five-database zero-residue queries: `0 / 0 / 0 / 0 / 0`
- final As-Built/install topology regression: `35 passed`, `1` protected skip
- NeX-WA Slice Gate: `318 passed`, `12` protected skips
- Slice statement/branch coverage: `97.30% / 94.70%`
- contract validation: `226 / 290 / 244 / 10`
- `git diff --check`: `PASS`

The P9-S30 Repository Full Gate remains the accepted canonical Full Gate:
`18,264 passed`, `131` protected skips, statement `96.01%`, branch `95.22%`,
and contract validation `226 / 290 / 244 / 10`.

## Exit

```text
P9-S31             = COMPLETE
P9 Foundation      = CLOSED
final As-Built     = FROZEN
next phase         = CONTROLLED DECISION REQUIRED
runtime/schema/API = UNCHANGED
```
