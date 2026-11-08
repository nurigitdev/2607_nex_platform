# P9-S30: Repository Full Gate and Reliability Closure

## Scope

P9-S30 closes the NeX-WA Foundation reliability boundary after P9-S21 through
P9-S29. It combines the ordinary Repository Full Gate with an explicitly
enabled P9 protected acceptance set against the actual AE, WC, OA, EOS, and WA
PostgreSQL test databases.

Remote embedding, reranking, and generation providers are not part of this
Foundation gate. The protected source-authority journey uses OA-signed service
tokens and service APIs; it does not use raw cross-service database reads.

## Reliability Acceptance

The protected acceptance set proves:

- current migrations and exact test database identities for all five services
- stale-worker fencing and recovery by a new lease owner
- crash-after-local-commit replay without duplicate evidence or assets
- dead-letter inspection, replay admission, and operator controls
- signed service trust with exact audience and minimum scopes
- installed WA API and evidence-consumer runtime admission
- the P9-S29 canonical source-authority, reconciliation, privacy, and
  concurrent-claim journey
- cleanup and zero owned residue

The explicitly enabled protected set completed with `41 passed`. The P9-S29
journey within that set used all five actual test databases and completed with
four WorkEvidence rows, three WorkAsset rows, three `PRIMARY` bindings, and
one `SUPPORTING` binding before cleanup.

## Repository Full Gate

```text
pytest                         = 18,264 passed, 131 skipped
statement coverage             = 96.01% (177,471 / 184,853 statements)
branch coverage                = 95.22% (40,110 / 42,122 branches)
required statement floor       = 96.00%
required branch floor          = 94.00%
contract schemas               = 226
contract examples              = 290
contract negative examples     = 244
OpenAPI documents              = 10
AE Web Node tests              = 403 passed
Repository Full Gate exit code = 0
```

The ordinary Full Gate retains explicit protected-resource skips. P9's actual
PostgreSQL acceptance was therefore forced separately before the Full Gate,
rather than being inferred from skipped tests.

## Baseline Comparison

The preceding successful Repository Full Gate recorded by P9-CA03 was:

```text
pytest              = 18,170 passed, 127 skipped
statement coverage  = 96.03%
branch coverage     = 95.27%
```

P9-S30 adds `94` passing tests and `4` protected skips. Statement coverage
changed by `-0.02` percentage points and branch coverage by `-0.05` percentage
points. The change is explained by the expanded WA runtime, deployment,
protected-smoke, and integration surfaces added after CA03; both executed-line
counts increased and both measures remain above their P9 floors. The focused
WA Slice Gate immediately before this closure remained higher at `97.30%`
statement and `94.70%` branch coverage. No unexplained coverage discontinuity
was found.

## Zero Residue

After the protected journey, tenant-prefixed residue queries were rerun against
the actual test databases:

```text
nex_wa_test   = 0
nex_ae_test   = 0
nex_wc_test   = 0
nex_oa_test   = 0
nex_eos_test  = 0
```

Only sanitized counts and decisions are retained. Tokens, database URLs, raw
source bodies, prompts, Artifact bytes, and private content are excluded.

## P9-CA04 Exit

```text
P9-S21 through P9-S30 = COMPLETE
Checkpoint Gate #3    = PASS
P9 protected E2E      = PASS
fault and recovery    = PASS
installed runtime     = PASS
contracts             = PASS
Repository Full Gate  = PASS
coverage floors       = PASS
zero residue          = PASS
P9 Foundation         = CLOSED
```

P9-S31 Final As-Built and handoff freeze remains a separate next Slice and is
not claimed by this closure.
