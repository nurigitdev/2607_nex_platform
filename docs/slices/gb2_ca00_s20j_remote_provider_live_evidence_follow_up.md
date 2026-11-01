# GB2-CA00-S20J Remote Provider Live Evidence Follow-Up

**Status:** PARTIAL - CALIBRATION DECISION REQUIRED

**Date:** 2026-11-02

**Entry baseline:** `5eb3ed06`

## 1. Scope

This follow-up executes the remote-provider checks that were explicitly
skipped during the S20J Repository Full Gate. It uses the canonical
`dgx_vllm` profile with the currently deployed generation, embedding, and
reranking providers. Protected evidence is written only below the ignored
`reports/live/` directory.

No provider endpoint, credential, prompt text, source text, or database
password is committed.

## 2. Provider and RAG Evidence

| Check | Result | Observation |
| --- | --- | --- |
| Provider TCP connectivity | PASS | generation, embedding, and reranking ports reachable |
| Canonical DGX profile preflight | PASS | configuration PASS, provider preflight 3/3 PASS |
| Protected provider requests | PASS | embedding dimension 2,560; reranking result returned; generation finish `STOP` |
| DB-less protected live RAG | PASS after correction | retrieval `READY`; rerank `APPLIED`; generation `COMPLETED` |
| PostgreSQL protected live RAG | PASS | `nex_cx_test`; migration current; persisted embedding dimension 2,560; cleanup complete |
| RAG score sample collection | PASS | 3/3 samples; all three passed the default threshold |
| S136 reranker calibration | FAIL | no threshold satisfied the frozen constraints |

## 3. Protected RAG Runner Correction

The first DB-less RAG execution reached all providers but failed generation
with `mo.remote_generation_response_invalid`: the provider returned no answer
text. The historical RAG runner omitted `reasoning_mode`, so the current
thinking-capable model used provider-default reasoning and exhausted the small
response budget before producing answer content.

AE's canonical generation client already sends `reasoning_mode=disabled`.
The protected RAG runner now follows the same public request contract and its
regression test verifies that the remote OpenAI-compatible payload contains:

```json
{"chat_template_kwargs": {"enable_thinking": false}}
```

Focused regression after the correction:

```text
23 passed
```

Both DB-less and PostgreSQL protected live RAG then passed.

The final CX Slice Gate used the changed DB-less runner as its per-file
coverage target while retaining both protected RAG regression files:

```text
pytest                         = 2,524 passed
statement coverage             = 99.01%
branch coverage                = 98.20%
changed runner statement       = 99.54%
changed runner branch          = 97.06%
contract validation            = PASS (227 / 291 / 245 / 10)
golden transition audit        = PASS
demo dependency audit          = PASS
commands                       = 7/7
```

## 4. Calibration Blocker

The live S136 calibration collected 36 labelled scores from
`Qwen3-Reranker-4B`, but returned `NO_ACCEPTABLE_THRESHOLD`.

```text
positive samples               = 12
negative samples               = 24
candidate thresholds           = 73
required maximum false-ready   = 0.10
required minimum ready recall  = 0.80
best-effort threshold          = 0.88611
best-effort false-ready rate   = 0.29166667
best-effort ready recall       = 0.66666667
best-effort balanced accuracy  = 0.6875
```

Positive and negative score ranges overlap materially. No candidate
calibration profile was admitted. The dataset, constraints, score semantics,
or provider request behavior must not be changed merely to make the smoke
green.

## 5. Decision and Remaining Live Runs

Execution stops at the calibration boundary. The following higher-level live
acceptance runs remain pending because they would otherwise create evidence on
top of an unresolved model-specific confidence policy:

- S136 permission-filtered hybrid retrieval PostgreSQL acceptance;
- S137 grounded generation and artifact PostgreSQL acceptance;
- S140 release-candidate live-provider matrix;
- S147 model-rollout live acceptance;
- S149/S150 protected release acceptance.

A focused calibration corrective Slice should first determine whether the
frozen dataset is representative, whether the provider's native score
semantics or request profile changed, and whether a multi-signal calibration
policy can meet the existing safety constraints.
