# GB2-CA00-S20Q-P-AD Extended Limited Shadow Runtime Operations

## Outcome

`GB2-CA00-S20Q-P-AD` is complete. The P-AC operator continuation decision is
now enforced by a fresh, restart-safe 30-provider-sample shadow window. The
protected acceptance decision is:

```text
EXTENDED_LIMITED_SHADOW_RUNTIME_OPERATIONS_ACCEPTED
```

The current `CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY` remains authoritative
for every user-visible decision. HOLDOUT access, primary policy mutation, raw
text projection, and production cutover remain prohibited.

## Fresh Window Policy

The immutable v2 policy binds the exact P-AC approval and the existing
controlled activation bundle:

```text
policy id             = cx-answer-support-extended-limited-shadow-operations-v2
policy hash           = sha256:c273eb6078573d96fb8bb25fb8478524a61c0020bf570c342c451ea1a3baa3d3
activation bundle     = sha256:6d5c631c9e18418ae2787d4053d06cdf87cc49a3cbc67aea6258b11f29893a06
review design         = sha256:f92c6d8e96b194383b19f9a9308696a2e29a833e2838be8c04dab492653477f9
operator decision     = sha256:bb7c3a3c077fa3471c2b84e83ad1a698e9246aa2662b96ae7b1468376a7ac510
decision receipt      = sha256:fae6534f558766d59f5eab53084cbc9e479f0de619bc30529ccba611f89988af
window id             = s20qpad-extended-limited-shadow-window-v1
provider sample cap   = 30
maximum concurrency   = 4
provider p95 SLO      = 15,000 ms
end-to-end p95 SLO    = 20,000 ms
provider failure cap  = 0
```

The legacy v1 12-sample policy and its validation semantics remain available
for historical evidence replay. Canonical Compose now selects the admitted v2
policy explicitly.

## Durable Window Boundary

No migration or new table was added. The runtime reuses
`service_operational_events` and writes a deterministic
`cx.retrieval.answer_support_shadow_window` open marker. Progress and outcomes
for v2 are counted only after that marker, so prior P-AB events cannot consume
the new allowance.

The marker ID is derived from `window_id`. Reopening the same policy is
idempotent, while using the same window ID with a different policy or approval
fails closed. Restart reconstructs the completed count from durable events and
does not reopen an exhausted window. Protected evidence cleanup removes the
marker and trace events without deleting historical source evidence.

## Protected Live Acceptance

The accepted run used the actual `nex_cx_test` PostgreSQL database and the
immutable Qwen3.5-9B generation deployment on port 9116. It issued seven c4
waves and one c2 wave, then tested the first post-cap request and a rebuilt
runtime:

```text
status                  = PASS
operations status       = REVIEW_REQUIRED
provider samples        = 30 / 30
provider calls          = 30
wave profile            = 8 waves, maximum c4
peak in flight          = 4
elapsed                 = 87.437285 seconds
provider p95            = 10,999.170554 ms
end-to-end p95          = 11,024.212 ms
post-cap request        = provider blocked
restart request         = provider blocked
test DB residue         = 0 rows
evidence hash           = sha256:b4956c90e5fe0896456fe9f62a12953b1d9bd1a6d2001f60a0942b23880d0cf2
```

Before the accepted run, protected admission rejected missing live provider
configuration, stale 4B revision/deployment defaults, and a missing test DB URL.
All three failures occurred before any provider request. The accepted run used
explicit endpoint, API key, model revision, deployment ID, and test DB URL
injection; none is persisted in source or evidence.

The ignored local evidence file is:

- `reports/live/gb2_ca00_s20qpad_extended_limited_shadow_operations.json`.

A direct PostgreSQL query independently confirmed zero remaining trace or
window-marker rows. The default-disabled invocation returned `SKIPPED` and
preserved the terminal PASS evidence.

## Verification

Focused verification before the final Slice Gate:

```text
focused tests             = 30 passed
shared v1/v2 runner       = 100% statement / 100% branch
P-AD protected runner     = 100% statement / 100% branch
limited operations module = 100% statement, three legacy partial branches
Ruff / py_compile         = pass
```

Final Slice Gate:

```text
NeX-CX regression          = 3,157 passed
statement coverage         = 99.23%
branch coverage            = 98.45%
limited operations module  = 100% statement / 97.22% branch
shared v1/v2 runner        = 100% statement / 100% branch
P-AD protected runner      = 100% statement / 100% branch
contract validation        = 230 schemas, 291 examples,
                             245 negative examples, 10 OpenAPI documents
golden transition audit    = pass
dependency audit           = pass
tiered Slice Gate          = 7/7 commands passed
```

## Next Boundary

`EXTENDED_LIMITED_SHADOW_OPERATOR_REVIEW_DECISION`

The next boundary may review this exact 30-sample evidence and decide whether
to continue shadow observation, retain the incumbent policy, or roll back the
observer. It must not rerun HOLDOUT or infer user-visible policy replacement or
production cutover from this acceptance.
