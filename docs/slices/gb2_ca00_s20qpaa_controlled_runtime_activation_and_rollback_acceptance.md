# GB2-CA00-S20Q-P-AA Controlled Runtime Activation and Rollback Acceptance

## Outcome

`GB2-CA00-S20Q-P-AA` is complete. The exact P-Z operator approval is now
installed as a bounded synchronous answer-support shadow observer in the CX
runtime composition. The protected acceptance decision is:

```text
CONTROLLED_RUNTIME_ACTIVATION_AND_ROLLBACK_ACCEPTED
```

This activation remains shadow-only. The existing retrieval confidence policy
continues to produce the authoritative user-visible decision. HOLDOUT access,
primary decision mutation, and production cutover remain prohibited.

## Installed Boundary

The canonical single-host Compose profile enables the controlled observer with:

```text
NEX_CX_ANSWER_SUPPORT_SHADOW_MODE=CONTROLLED
NEX_CX_ANSWER_SUPPORT_ACTIVATION_BUNDLE_PATH=
  /app/services/nex-cx/nex_cx/data/answer_support_controlled_activation.v1.json
```

The service default outside this deployment profile remains `DISABLED`.
Controlled startup validates the complete immutable bundle before building the
observer. Missing, malformed, drifted, or unapproved evidence fails closed.

The observer is wired through the existing `HybridRetrievalShadowObserver`
boundary. The primary retrieval package is built first and defensive copies are
passed to the observer, so shadow failure or rollback cannot modify the primary
package.

## Immutable Activation Bundle

The installed bundle is:

```text
bundle hash             = sha256:6d5c631c9e18418ae2787d4053d06cdf87cc49a3cbc67aea6258b11f29893a06
P-Z receipt hash        = sha256:7cff54fcae3f2413128f3e289b57062133a6fd72fbdfed1ea4eb5931aa5f8191
operator decision hash  = sha256:4eb6b8951e25a69cdc59c81b27be13d5b492e0dbb5327c901d58986002c0caa2
operator manifest hash  = sha256:b124a623be130bed54abe225f724a508db43e45ff7d3bb921c79718fd0751f1e
selected policy hash    = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
provider binding hash   = sha256:e16f1c5a52d8a423383a82b6afab80561a4de376b574f3a1b91b9d139dde3012
model revision          = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
deployment              = dgx-qwen3-5-9b-9116
maximum in flight       = 4
```

The bundle is committed under the CX package so OCI images contain the exact
runtime input. Ignored `reports/live` files are evidence only and are never a
runtime dependency.

## Durable State and Rollback

No database migration or new table was added. Activation and rollback state use
the existing `service_operational_events` store with deterministic event IDs.
Progress and sanitized shadow outcomes use the same operational event boundary.
Raw query or evidence text is not persisted by the activation controller.

Rollback is sticky across process restart. A persisted `ROLLED_BACK` state takes
precedence over `ACTIVE`, and subsequent startup does not reconstruct the
observer for that bundle. Immediate rollback is performed for:

- provider binding drift;
- provider failure or invalid provider response;
- progress sink failure; and
- unexpected or non-retryable overload.

Feedback, provider, or end-to-end p95 SLO breach rolls back after the approved
minimum four-sample window. Every rollback returns control to
`CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY`.

## Protected Live Acceptance

The protected runner used the actual `nex_cx_test` PostgreSQL database and the
live Qwen3.5-9B generation provider on the approved 9116 deployment. Four
requests were issued concurrently; no HOLDOUT data was read.

```text
status                   = PASS
sample count             = 4
provider calls           = 4
peak in flight           = 4
elapsed                  = 11.074398 seconds
provider p95             = 11,011.355004 ms
end-to-end p95           = 11,062.783 ms
active restart recovery  = verified
injected provider fault  = rolled back
rollback reason          = PROVIDER_ERROR
rollback restart block   = verified
persisted rollback       = verified
test DB residue          = 0 rows
evidence hash            = sha256:de971f99e9f0d60e73a65f2d5a7deeb28ca31782759e483c565134dfeba18d0a
```

The ignored local evidence file is:

- `reports/live/gb2_ca00_s20qpaa_controlled_runtime_activation.json`.

The runner deletes its deterministic activation, progress, and outcome evidence
rows after verification. A direct query confirmed zero test residue.

## Verification

Focused verification:

```text
focused tests             = 19 passed
product activation module = 100.00% statement / 100.00% branch
protected runner           = 98.83% statement / 95.00% branch
related CX regression      = 97 passed
format/static checks       = pass for new and changed boundary modules
```

Final Slice Gate:

```text
NeX-CX regression         = 3,123 passed
statement coverage        = 99.20%
branch coverage           = 98.43%
contract validation       = 230 schemas, 291 examples,
                            245 negative examples, 10 OpenAPI documents
golden transition audit   = pass
dependency audit          = pass
tiered Slice Gate         = 7/7 commands passed
```

The default-disabled smoke invocation returned `SKIPPED` and preserved the
terminal protected evidence.

## Next Boundary

`LIMITED_SHADOW_RUNTIME_OPERATIONS`

The next boundary may operate this exact controlled observer for a limited
window, expose sanitized operator health and rollback state, and collect enough
runtime evidence for a later operator decision. It must not reinterpret this
acceptance as authorization for user-visible policy replacement or production
cutover.
