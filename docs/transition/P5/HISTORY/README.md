# P5 Design History

This directory preserves superseded P5 transition baselines and received
review packages. Files here are historical evidence and are not implementation
authority.

## Current Authority

The canonical P5 implementation baseline is the v1.1 document and contract set
in `docs/transition/P5/`. Its authority order and required reading sequence are
defined by the canonical `README.md`.

## Historical Baselines

- `v1.0/` preserves the complete former canonical P5 v1.0 document set,
  including its README and transition contracts.
- `packages/P5_CA01A_v1.1/` preserves the received v1.1 review package exactly
  as delivered so its CSV manifest can be revalidated.

`P5_CA01_Frozen_Source_Manifest_v1.0.csv` intentionally remains in the
canonical P5 directory. CA01A changes the transition interpretation and
machine contracts, not the reviewed Frozen source bytes recorded by that
manifest.

Implementation SHALL NOT resolve schemas or design rules from `HISTORY/`.
