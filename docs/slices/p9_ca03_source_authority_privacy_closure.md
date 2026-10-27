# P9-CA03: Source Authority and Privacy Closure

## Scope

P9-S11 through P9-S20 are closed against the real source-service boundaries.
NeX-WA reads AE, WC, OA, and EOS only through protected service APIs; it does
not read another service's database directly. WA persists only the admitted
reference, hash, classification, authority, and lineage projections in its own
database.

The protected integration uses these actual test database identities:

| Service | Database | User |
| --- | --- | --- |
| NeX-AE API | `nex_ae_test` | `nex_ae_user` |
| NeX-WC | `nex_wc_test` | `nex_wc_user` |
| NeX-OA | `nex_oa_test` | `nex_oa_user` |
| NeX-EOS | `nex_eos_test` | `nex_eos_user` |
| NeX-WA | `nex_wa_test` | `nex_wa_user` |

## Protected Source Acceptance

The source-backed PostgreSQL test creates signed OA RSA service credentials
and verifies exact audiences and scopes:

- WA to AE and WC: `service:call`, `work:source:read`
- WA to OA: `service:call`, `identity:subject:verify`
- WA to EOS: `service:call`, `project:verify`
- protected WA detail reads: audience `nex-wa` and cumulative detail scope

The journey proves that a pre-ACK AgentResult is rejected, the same result is
admitted after its required delivery is acknowledged, a WC WorkResult is bound
once as `SUPPORTING`, and a Human-owned READY Artifact is admitted only after
OA subject verification. EOS project and membership verification remains a
separate authority check. Wrong audience, missing detail scope, and
cross-tenant reads fail closed.

The accepted aggregate contains three WorkEvidence rows and two WorkAsset
rows with roles `PRIMARY`, `PRIMARY`, and `SUPPORTING`. Cleanup removes all
CA03 rows from WA and every seeded source row from AE, WC, OA, and EOS, proving
zero owned test residue.

Source hash conflict, immutable supersession, correction, and historical audit
lineage remain covered by the P9-S20 regression suite. CA03 does not duplicate
those semantics in its protected database journey.

## Baseline Reconciliation

The first Repository Full Gate found no runtime regression. It found two WA
positive examples that were valid but absent from `contracts/examples/index.json`.
Registering those examples restored P8 contract hygiene. The historical S101
closure also used an absolute contract-drift count of `33`; it now derives the
expected count from the current classified drift-item inventory, preserving
fail-closed classification while allowing the repository to grow.

## Verification

```text
actual AE/WC/OA/EOS/WA PostgreSQL smoke = 1 passed
focused P9-S11..S20 regression           = 153 passed, 1 protected skip
NeX-WA Slice Gate                        = 314 passed, 9 skipped
NeX-WA statement coverage                = 97.35%
NeX-WA branch coverage                   = 94.92%
focused hygiene/S101 reconciliation      = 21 passed
Repository Full Gate                     = 18,170 passed, 127 skipped
repository statement coverage            = 96.03%
repository branch coverage               = 95.27%
contract validation                      = 225 schemas, 289 examples,
                                           241 negative examples, 10 OpenAPI
zero owned residue                       = PASS
P9-CA03                                  = PASS
```

The ordinary Full Gate intentionally skips protected external-resource tests.
The CA03 PostgreSQL journey was separately forced with its explicit opt-in and
completed against all five actual test databases before the Full Gate.

## Exit

```text
S11-S20 complete          = PASS
signed service trust      = PASS
source authority          = PASS
privacy scope separation = PASS
cross-service DB reads    = NONE
zero residue              = PASS
next Slice                = P9-S21
```
