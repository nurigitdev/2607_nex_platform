# GB2-CA00-S20Q-P-AF Answer-Support Policy Cutover Operator Decision

## Outcome

`GB2-CA00-S20Q-P-AF` is complete. The Slice consumes the exact P-AE review
receipt, P-AE report, and immutable controlled-activation bundle and records
this explicit operator decision:

```text
CONTROLLED_ANSWER_SUPPORT_POLICY_CUTOVER_APPROVED
```

The decision status is `APPROVED_NOT_EXECUTED`. It authorizes the selected
answer-support policy for a separate installed cutover-and-rollback acceptance.
It does not change runtime wiring, make the candidate user-visible, rerun
HOLDOUT, call a provider or database, or approve platform production cutover.

## Immutable Source Boundary

The operator decision binds the exact P-AE decision lineage:

```text
P-AF design hash          = sha256:67caf7cd029bca7422b70b0bd15b097d39b4b04e2ec123f0e45b99cac8aa2304
P-AE design hash          = sha256:ddc6c73d885ec58c6c09fc3e15aa77483b2b64ecb1a077406c075632e84188df
P-AE operator decision    = sha256:42adc3ad9b71c64719fcf8178bf9b4b3ac4106a4b25aafe1bf8b8fa1c83b906c
P-AE manifest hash        = sha256:ae841b1ee41e32c18c2445e56463ac05753cb67446d36b7301754b972c2649bc
P-AE receipt hash         = sha256:f93bf3806460b539951473535dcf3cc89dcd49a4186e37c8a850f52f7cc04e9b
P-AE receipt document     = sha256:e1cfe99601599be3c1d61f686d8f9a99b9f014e0066ce3df6e970406390292be
P-AE report document      = sha256:55b73669444f0569ab2e9292dbf8eb873fe9e00a8cb9d87ea783079bd4570749
P-AD operations evidence = sha256:b4956c90e5fe0896456fe9f62a12953b1d9bd1a6d2001f60a0942b23880d0cf2
```

It separately validates the committed activation bundle and its complete
HOLDOUT, provider, E2E, runtime, and rollback lineage:

```text
activation bundle hash = sha256:6d5c631c9e18418ae2787d4053d06cdf87cc49a3cbc67aea6258b11f29893a06
bundle document hash   = sha256:ecbe2e072066e9a599b9462f9616c14e9381f2818167e1fc61a6eaf28c090b84
selected policy hash   = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
provider binding hash  = sha256:e16f1c5a52d8a423383a82b6afab80561a4de376b574f3a1b91b9d139dde3012
readiness manifest     = sha256:77fb8be58e0c06cc91e9397a2f7d0d32787de1e9b7d844dc45942035e635bf8b
```

The approval targets these immutable contracts rather than a model name.
Provider revision, policy, request profile, activation bundle, or source
evidence drift fails closed before a decision receipt is written.

## Approved Boundary

```text
approved scope             = CONTROLLED_ANSWER_SUPPORT_USER_VISIBLE_POLICY_CUTOVER
selected policy            = c81f7a...168cb
current policy              = CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY
fallback / rollback target  = CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY
policy cutover approved     = true
policy cutover executed     = false
user-visible change approved = true
user-visible change executed = false
runtime changed             = false
production cutover          = prohibited
```

Immediate rollback remains mandatory for source-binding drift, provider error,
progress-sink failure, and non-retryable overload. Feedback, provider, or E2E
p95 SLO breach requires rollback pending operator review. The next boundary
must prove these controls in the installed composition before the policy can
remain authoritative.

## Evidence Reviewed

```text
extended provider samples = 30 / 30
provider calls            = 30
peak in flight            = 4
provider p95              = 10,999.170554 ms
end-to-end p95            = 11,024.212 ms
provider failures         = 0
test DB residue           = 0 rows
```

These P-AD metrics supplement the earlier one-shot HOLDOUT, synchronous E2E,
controlled activation, rollback, restart, and initial 12-sample limited-window
evidence. No evidence was recollected in this Slice.

## Protected Decision Evidence

The one-shot protected decision produced a mode-`0600` receipt:

```text
operator decision hash = sha256:2ad36debb60868f6712805c779d65779c3b9bc160ce39fd8f418bf45b354e2ff
manifest hash          = sha256:e8c73a47aad709da1bdbca9370f37ccd53e265959e6c1853d0826c2a392fa2a6
decision receipt hash  = sha256:eb8cfb71a05d08dca37196e1b57608e2f90584e2d932635a881e7c14ac14f23c
provider calls         = 0
database calls         = 0
HOLDOUT accessed       = false
cutover executed       = false
runtime changed        = false
```

The ignored local evidence files are:

- `reports/live/gb2_ca00_s20qpaf_answer_support_policy_cutover_decision.json`;
- `reports/live/gb2_ca00_s20qpaf_answer_support_policy_cutover_decision_receipt.json`.

The default-disabled invocation returned `SKIPPED` and preserved the terminal
decision evidence.

## Verification

```text
focused tests              = 16 passed
adjacent P-AA/P-AE tests   = 53 passed
product decision module    = 100% statement / 100% branch
protected runner           = 100% statement / 100% branch
Ruff / py_compile          = pass

NeX-CX Slice Gate          = 3,172 passed
statement coverage         = 99.23%
branch coverage            = 98.46%
contract validation        = 230 schemas, 291 examples,
                             245 negative examples, 10 OpenAPI documents
golden transition audit    = pass
dependency audit           = pass
tiered Slice Gate          = 7/7 commands passed
```

## Next Boundary

`ANSWER_SUPPORT_POLICY_CUTOVER_AND_ROLLBACK_ACCEPTANCE`

The next boundary may install the exact approved policy as the authoritative
user-visible answer-support decision, exercise normal, restart, replay, and
forced rollback paths, and verify immediate fallback to the incumbent policy.
It must bind this P-AF receipt and must not reinterpret policy cutover as a
platform-wide production release decision.
