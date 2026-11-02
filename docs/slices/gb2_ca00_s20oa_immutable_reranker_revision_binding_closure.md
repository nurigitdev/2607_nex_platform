# GB2-CA00-S20O-A: Immutable Reranker Revision Binding Closure

## Status

`CLOSED - LIVE IMMUTABLE REVISION BOUND`

S20O identified one remaining provider-runtime gap: NeX-MO used the mutable
served model name as `model_revision`. S20O-A closes only that gap. It does
not activate a calibration threshold, open the sealed holdout, or weaken the
S20N false-ready and recall constraints.

## Identity Contract

The following values now have separate meanings:

| Field | Meaning |
| --- | --- |
| `model_name` | Mutable vLLM request/served name, currently `Qwen3-Reranker-4B` |
| `model_revision` | Immutable artifact identity, `hf:<40-hex>` or `sha256:<64-hex>` |
| `deployment_id` | Runtime deployment identity, currently `vllm-reranker-http` |

An immutable revision must not be inferred from `/v1/models`, the served
name, a filesystem directory name, or an operator label. The current DGX
profile is bound to:

```text
hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
```

The served model name remains unchanged so the OpenAI-compatible request
contract is not coupled to a Hugging Face commit hash.

## Artifact Attestation

`inspect_model_artifact_revision.py` reads the local Hugging Face download
metadata under the model owner's authority. Admission is fail-closed when:

- metadata is missing or malformed;
- metadata entries contain more than one source commit;
- a metadata target is missing;
- no weight artifact exists;
- the evidence contains a model path or artifact content;
- the configured revision differs from the attested revision.

Evidence retains only counts, the immutable revision, and a metadata manifest
digest. It does not retain the model path, checkpoint bytes, endpoint, API
key, query, or document text.

The DGX attestation observed:

```text
metadata files        = 16
metadata targets      = 16
weight artifacts      = 2
artifact revision     = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
metadata manifest     = sha256:d01352230b77d40e523080f6c4d05a150b9ae0baa364ee5e40bf541493864c9a
```

## Runtime Binding

The current DGX canonical profile and `.env.example` now bind
`NEX_MO_REMOTE_RERANKER_MODEL_REVISION` to the attested revision. The
S20O-A protected runner verifies all of the following in one evidence record:

1. artifact attestation admission;
2. the earlier S20O runtime gap was revision binding only;
3. configured revision equals the artifact revision;
4. served name remains separate from artifact revision;
5. normalized live response carries the artifact revision;
6. deployment identity remains stable;
7. an actual two-document rerank response is correctly ordered.

The protected call returned two results in expected index order with scores
`0.465360` and `0.118453`. The evidence itself remains under the ignored
`reports/live/` tree.

## Operator Commands

The model owner produces a redacted attestation on the DGX host:

```bash
python3 /tmp/inspect_model_artifact_revision.py \
  --model-directory /home/nurivoice-dgx/models/Qwen/Qwen3-Reranker-4B \
  --output /tmp/gb2_s20oa_reranker_revision.json \
  --summary
```

The protected binding runner then consumes that evidence with the existing
protected NeX-MO provider environment:

```bash
export NEX_GB2_S20OA_RERANKER_LIVE=1
export NEX_GB2_S20OA_ARTIFACT_EVIDENCE_PATH=reports/live/gb2_s20oa_reranker_revision.json
export NEX_MO_REMOTE_RERANKER_MODEL_REVISION=hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
./.venv/bin/python scripts/smoke/run_gb2_s20oa_immutable_reranker_binding.py \
  --summary \
  --output reports/live/gb2_ca00_s20oa_immutable_reranker_binding.json
```

Provider endpoints and credentials must continue to come from protected
environment injection and must not be committed.

## Verification

```text
DGX artifact attestation       = PASS
protected live binding         = PASS
live result count              = 2
focused regression             = 151 passed
new boundary focused coverage  = statement 98% / branch 100%
platform Slice Gate            = PASS
Slice Gate regression          = 427 passed / 8 protected skips
Slice Gate statement           = 97.35%
Slice Gate branch              = 95.95%
nex-mo Slice Gate              = PASS
nex-mo regression              = 1306 passed / 6 protected skips
nex-mo statement               = 99.80%
nex-mo branch                  = 99.39%
nex-runtime regression         = 2033 passed / 1 protected skip
nex-runtime new module         = statement 96% / branch 100%
contract validation            = PASS (228 schemas / 291 examples /
                                 245 negative examples / 10 OpenAPI documents)
golden journey audit           = PASS
demo/product dependency audit  = PASS
```

The broad `nex-runtime` service gate is not an admitted gate result: it
includes legacy shared modules that its service test inventory does not
exercise and therefore reports statement `88.47%` and branch `85.72%`
against `95%`/`94%` thresholds. All 2,033 selected tests passed, the new
module has no uncovered branches, and the authoritative platform and NeX-MO
Slice Gates pass. Reconciliation of that pre-existing service coverage scope
belongs to the quality-gate baseline rather than this revision-binding Slice.
