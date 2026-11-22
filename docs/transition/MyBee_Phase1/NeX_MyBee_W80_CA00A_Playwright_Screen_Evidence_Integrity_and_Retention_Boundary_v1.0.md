# NeX MyBee W80-CA00A Playwright Screen Evidence Integrity and Retention Boundary v1.0

**Status:** CONTROLLED AMENDMENT / IMPLEMENTED / LIVE CLOSURE BLOCKED

**Boundary:** W80-CA00 diagnostic evidence -> W80-CA01 entry

**Database migration or backend business API change:** None

## 1. Purpose

The protected M1 journey produced sixteen PNG files, but source-backed review
found that API completion and visual completion were not the same assertion.
The first transaction result could be captured before the React result card was
rendered, and the post-restart capture could show an empty workspace while the
authoritative API projection had already passed. A PASS receipt therefore did
not guarantee that every named screenshot proved its claimed user-visible
state.

W80-CA00A makes screen evidence semantic, integrity-bound, private, and
retention-governed before W80 accounting work begins.

## 2. Canonical Decisions

1. A sleep or successful API response is not a visual assertion.
2. Every semantic capture must wait for its expected accessible DOM state.
3. Transaction result evidence requires the exact submitted request and the
   visible voucher-result card with terminal `완료` state.
4. Restart recovery evidence requires an authenticated owner-scoped interaction
   result to be rendered in the workspace. An empty workspace is a failure.
5. Approval evidence requires the decision-recorded surface before capture.
6. Failure paths retain a separately labelled diagnostic capture without
   replacing the original failure.
7. Screenshots contain private business data and inherit the W80-CA00
   restricted-evidence classification.

## 3. Manifest Contract

Journey and recovery processes each write an atomic mode `0600` manifest under
a mode `0700` screen directory. Every entry contains only bounded metadata:

- stage and expected semantic state;
- assertion identifier;
- captured timestamp;
- file name, byte size, and SHA-256;
- viewport dimensions;
- interaction lineage and transaction index where applicable.

Raw prompts, passwords, tokens, database URLs, request bodies, and response
bodies are forbidden in the manifest. The PNG itself is the restricted visual
record and is never committed.

## 4. Required Visual States

The protected two-transaction M1 journey must preserve at least:

| State | Minimum |
| --- | ---: |
| login required | 2 |
| requester workspace ready | 1 |
| business approver workspace ready | 1 |
| accounting approver workspace ready | 1 |
| request admitted | 2 |
| approval recorded | 6 |
| result rendered | 2 |
| result recovered after restart | 1 |

Missing files, unsafe paths, byte-size mismatch, digest mismatch, omitted DOM
assertions, or missing required states fail the protected journey.

## 5. Recovery Surface

The installed AE Web workspace accepts an owner-scoped `interaction_id` query
to re-read the existing AgentResult through the admitted AE facade. It renders
only the existing safe business-result projection. The backend remains the
authority, owner/tenant authorization remains fail-closed, and no fixture,
M1-specific value, or new persistence structure is introduced.

## 6. Retention and Collection

Before Compose teardown, both PNG files and manifests are verified and copied
under `<diagnostic-session>/screens/`. The final recursive W80 manifest then
covers Docker logs, structured diagnostic events, screenshots, and screen
manifests together. The existing seven-day default and thirty-day maximum
retention apply. The source and collected report directories remain ignored by
Git.

## 7. Acceptance

Acceptance requires:

1. focused Node and React tests for manifest integrity and visible recovery;
2. focused Python tests for collection, required-state counts, and final
   manifest inclusion;
3. AE Slice Gate with existing coverage thresholds retained;
4. exact-head OCI/Compose deployment;
5. actual PostgreSQL, OpenBao, RustFS, Qwen3.5-9B, authenticated Playwright,
   restart recovery, and zero-residue cleanup;
6. visual review of the new result and recovered-result captures.

## 8. Decision

```text
SCREEN PASS FROM API ONLY        = FORBIDDEN
SEMANTIC DOM ASSERTION           = REQUIRED
SCREEN FILE HASH / SIZE BINDING  = REQUIRED
RESTART RESULT VISIBLE IN UI     = REQUIRED
RESTRICTED SESSION COLLECTION    = REQUIRED
DATABASE MIGRATION               = NONE
BACKEND BUSINESS API CHANGE      = NONE
```

## 9. Exact-Head Verification and Live Finding

The screen-evidence implementation was frozen in commit `128048a3` and passed:

- focused Node and React tests;
- AE Web regression, typecheck, and production build;
- the AE Slice Gate with statement coverage `96.45%` and branch coverage
  `94.67%`;
- exact-head nine-image OCI build and AE product-runtime image admission;
- live DGX preflight for Qwen3.5-9B, Qwen3-Embedding-4B, and
  Qwen3-Reranker-4B.

The actual eight-database PostgreSQL/OpenBao/RustFS/DGX/Playwright run then
failed closed on the first transaction result assertion. The protected product
flow reached all three approvals and completed the authoritative EOS voucher,
journal, allocation, and P&L calls. The IA AgentResult was terminal
`SUCCEEDED`, but its public projection contained neither `business_refs` nor
`business_summary`; AE Web therefore rendered the admitted generic
`request-processing result` card instead of the required voucher-result card.

Source-backed diagnosis found that the existing WC `WORK_RESULT_SUBMITTED`
event and AE delegated-result continuation preserve technical and business
outcomes plus lineage references, but do not carry the background AgentResult
structured business result. The screen-evidence boundary correctly rejected
this visually incomplete success. Relaxing the DOM assertion is forbidden.

The run retained failure evidence, removed all eight isolated schemas, and
reported `zero_residue=true`. W80-CA00A remains implemented, but its live
closure and W80 entry require a separate corrective contract for durable,
typed business-result propagation from the PA WorkResult to the originating IA
AgentResult. No database or backend business API change is authorized by this
amendment.
