# GB2-CA00-S20Q-P-N: Provider-Backed Fresh CALIBRATION Collection

## Status

`CLOSED - fresh provider evidence collected; P-O calibration required`

## Scope

P-N evaluates every package admitted by P-M with one immutable generation
artifact and the existing reasoning-disabled answer-support request profile. It
does not access Dataset v4 HOLDOUT, select a threshold, compare profiles, or
activate runtime policy.

The collection used the protected DGX route at port `9116` and bound the
request to `Qwen3.5-9B`. Endpoint and API-key values are not persisted in the
evidence. The prior port `9111` route was not used.

## Provider Binding

```text
provider type          = vllm
provider alias         = general-llm-default
deployment             = dgx-qwen3-5-9b-9116
model                   = Qwen3.5-9B
artifact revision       = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
artifact evidence hash = sha256:50135139c4271768dde60328dd46ddceab663b8e66928746e21affe82ff7955e
request profile         = s136-answer-support-generation-json-v1
score semantics        = bounded-ordinal-answer-support-v1
maximum concurrency    = 4
```

## Collection Result

```text
CALIBRATION packages       = 200
candidates                 = 800
provider HTTP requests     = 200
provider evaluations       = 200
database calls             = 0
HOLDOUT cases accessed     = 0
runtime activation         = prohibited
profile/threshold selection = prohibited
```

Provider classifications were:

```text
CONTRADICTORY_EVIDENCE = 100
DIRECT_ANSWER          = 100
INSUFFICIENT_CONTEXT   =   6
SUPPORTING_EVIDENCE    = 100
TOPICAL_NON_ANSWER     = 494
```

The evidence contains query and candidate hashes, bounded scores, provider
classifications, and request lineage. It does not persist query text,
candidate text, provider output text, API keys, endpoints, or candidate truth
labels.

## Integrity Binding

```text
P-M fresh dataset = sha256:dab6ef0d8ba09ea8b22fdd0f7a1f8bd937748c80e2a3f170c0caabfcbf44148b
P-N collection    = sha256:9ed7ed8c3a699d48c7090223749d60fe40574bae6e2520822cd0fc9d52749d4b
```

The ignored protected report is
`reports/live/gb2_ca00_s20qpn_fresh_answer_support_collection.json`.

## Implementation

`collect_answer_support_calibration()` now accepts a validated request
namespace. Its default remains `s20qpi`, preserving the predecessor evidence
contract, while P-N uses `s20qpn` to make fresh request lineage unambiguous.

`run_gb2_s20qpn_fresh_answer_support_collection.py` reconstructs and admits
the P-M dataset, verifies the P-L/P-M/P-I source bindings, performs one live
provider evaluation per package, and emits text-free immutable evidence.

## Verification

```text
focused product/runner tests          = 27 passed
new product statement/branch          = 100% / 100%
new protected runner statement/branch = 100% / 100%
protected live provider collection     = PASS
NeX-CX Slice Gate direct/impact tests  = 208 passed
repository statement coverage         = 99.12%
repository branch coverage            = 98.30%
contract validation                    = PASS
golden journey transition audit        = PASS
demo-to-product dependency audit       = PASS
```

P-N does not prove generalization. P-O may calibrate only the single P-L
canonical profile against this fresh CALIBRATION collection. Dataset v4
HOLDOUT remains sealed until a later explicitly admitted acceptance Slice.
