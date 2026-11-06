# GB2-CA00-S20Q-P-AG Answer-Support Policy Cutover and Rollback Acceptance

## Outcome

`GB2-CA00-S20Q-P-AG` is complete. The exact answer-support policy approved in
P-AF is now available as the authoritative retrieval confidence decision in
the canonical CX composition under the explicit `CONTROLLED` profile.

The cutover changes only the final confidence/status projection. It does not
change permission scope, candidate order, evidence text, or the hybrid
retrieval result. `DISABLED` remains the library default; the canonical
Docker Compose profile opts in explicitly.

## Immutable Authorization

The installed authorization artifact is:

```text
services/nex-cx/nex_cx/data/answer_support_policy_cutover_authorization.v1.json
```

It binds the exact P-AF receipt and prior activation bundle:

```text
P-AF receipt hash       = sha256:eb8cfb71a05d08dca37196e1b57608e2f90584e2d932635a881e7c14ac14f23c
authorization hash      = sha256:fe45b9267af3e81095b957c0488ee86dba7f88114b3fff99708ccc812108fc00
activation bundle hash  = sha256:6d5c631c9e18418ae2787d4053d06cdf87cc49a3cbc67aea6258b11f29893a06
selected policy hash    = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
provider binding hash   = sha256:e16f1c5a52d8a423383a82b6afab80561a4de376b574f3a1b91b9d139dde3012
```

Receipt, bundle, selected policy, request profile, provider deployment, or
model revision drift fails before cutover activation.

## Runtime Composition

`PermissionFilteredHybridPackageRuntime` now has a dedicated
`HybridRetrievalPrimaryPolicy` extension point. The answer-support cutover
adapter runs after owner-scoped evidence materialization and before the
package is returned. A normal result updates the existing v1 confidence
projection and regenerates the package identity while preserving:

- owner and tenant permission snapshot;
- evidence item identities, order, and private text;
- BM25/vector/RRF/reranker candidate ordering;
- existing retrieval context package v1 schema compatibility.

The old shadow and limited-shadow observers are not invoked when controlled
cutover is active, so one retrieval request produces one provider evaluation.

## Durable State and Rollback

No migration or new table was added. Activation and terminal fallback states
use the existing `service_operational_events` store with event type:

```text
cx.retrieval.answer_support_policy_cutover
```

State event IDs are deterministic. Restart reconstructs `ACTIVE`,
`ROLLED_BACK`, or `ROLLBACK_PENDING_REVIEW` without replaying a provider call.
The persisted digest field is named `cutover_receipt_hash`; this avoids the
generic operational-event secret redactor that correctly redacts keys named
`authorization_hash`.

Immediate fallback is enforced for source-binding drift, provider failure,
progress-sink failure, and non-retryable overload. Feedback, provider, and
interactive E2E p95 breaches enter `ROLLBACK_PENDING_REVIEW`. Both terminal
states return the incumbent package without another provider call.

## Protected Live Acceptance

The protected runner used the actual `nex_cx_test` PostgreSQL database and the
immutable Qwen3.5-9B provider profile on the admitted DGX endpoint.

```text
sample count             = 4
provider calls           = 4
maximum concurrency      = 4
provider p95             = 11,015.878888 ms
end-to-end p95           = 11,063.127 ms
elapsed wall time        = 11.073552 s
active restart recovery  = PASS
forced provider rollback = PASS / PROVIDER_ERROR
rollback restart fallback= PASS
permission preservation  = PASS
evidence preservation    = PASS
test DB residue          = 0 rows
```

The first protected attempts stopped before provider execution because the
generation endpoint/API key and then the test DB URL were absent. A further
attempt correctly rejected stale Qwen3.5-4B defaults against the immutable
Qwen3.5-9B binding. The successful run explicitly supplied the admitted
endpoint, revision, deployment, and `nex_cx_test` URL. These are configuration
admission results, not relaxed runtime checks.

Ignored local evidence:

```text
reports/live/gb2_ca00_s20qpag_answer_support_policy_cutover_acceptance.json
evidence hash = sha256:c07655bcba5fc85db6506bbcba873dbb33d3ed91fd2395cd266837df18545aac
```

## Verification

```text
focused and adjacent tests = 149 passed
new module/runner coverage = 98% combined
product cutover module      = 99% focused, 98% CX Slice Gate
protected live acceptance  = PASS
canonical Compose audit    = PASS
canonical deployment tests = 66 passed

NeX-CX Slice Gate          = 3,180 passed
statement coverage         = 99.22%
branch coverage            = 98.43%
contract validation        = 230 schemas, 291 examples,
                             245 negative examples, 10 OpenAPI documents
golden transition audit    = PASS
dependency audit           = PASS
tiered Slice Gate          = 5/5 commands passed
```

## Next Boundary

`ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS`

The next boundary should observe the controlled user-visible policy over a
bounded operational window. It must retain the P-AG authorization and rollback
state, must not rerun the one-shot HOLDOUT, and must not reinterpret this CX
policy cutover as a platform production release decision.
