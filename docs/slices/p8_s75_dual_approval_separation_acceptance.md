# P8-S75: Dual Approval Separation Acceptance

## Status

Completed on 2026-10-23.

## Scope

P8-S75 closes P8.7 by proving that the three human-approval domains are
different authorities with different evidence and systems of record:

| Domain | Provider | Protected target | Terminal evidence |
|---|---|---|---|
| `AGENT_FORMAL` | `AGENT` | agent runtime action | agent approval decision |
| `NSL_WRITE` | `NSL` | exact NSL ApprovalRequest and write intent | Platform ApprovalEvidence |
| `BUSINESS_FORMAL` | `EOS` | exact EOS ApprovalStage and BusinessOperation | final EOS ApprovalProof |

Sharing the WC approval inbox and decision transport does not make these
domains interchangeable. WC preserves the domain and provider on every work
item; the receiving system validates its own exact lineage before mutation.

## Separation Acceptance

The acceptance suite exercises public production boundaries and proves:

1. `NSL_WRITE`, `BUSINESS_FORMAL` and `AGENT_FORMAL` map to distinct providers.
2. EOS admits only a `BUSINESS_FORMAL` work item bound to the expected EOS
   ApprovalStage, BusinessOperation and decision event.
3. Platform ApprovalEvidence built from an NSL request cannot enter the EOS
   business-approval transition boundary.
4. An EOS `BUSINESS_FORMAL` work item or ApprovalProof cannot satisfy the
   `NSL_WRITE` evidence builder.
5. An `AGENT_FORMAL` work item cannot satisfy either protected write boundary.
6. Every rejected substitution is fail-closed before a sink or repository
   mutation.

No production API, schema or migration was added. The existing AE, WC and EOS
validation boundaries were sufficient; this Slice adds explicit acceptance
coverage for their composition.

## Protected PostgreSQL Evidence

The protected acceptance pack used the actual local PostgreSQL test databases
owned by AE, WC, OA and EOS. It completed with `8 passed`, zero skips:

- AE and WC persisted the NSL approval request, decision and immutable Platform
  ApprovalEvidence and verified exact idempotent replay.
- WC performed two fresh OA authority reads for a two-stage
  `BUSINESS_FORMAL` approval.
- EOS advanced both stages, issued the final ApprovalProof, restored it after
  repository restart and accepted only an exact replay.
- All protected-smoke rows were removed and zero residue was verified.

Remote embedding, reranking and generation providers were not required.

## Regression And Full Gate

- Focused P8-S75 acceptance: `6 passed`.
- Focused P8 approval regression: `365 passed`.
- Repository Full Gate: `16,983 passed`, `92` protected skips.
- Statement coverage: `96.78%` with a `95%` threshold.
- Branch coverage: `96.21%` with an `85%` threshold.
- Contracts: `188` schemas, `250` examples, `217` negative examples and `9`
  OpenAPI documents.
- AE Web regression: `359 passed`, zero failures and zero skips.
- Full Gate process exit code: `0`.

Protected smoke tests remain opt-in in the ordinary Full Gate. The required
four-database P8-S75 acceptance pack was executed separately with all protected
flags enabled and no skip.

## Exit Decision

P8-S75 is closed. The P8.7 approval-domain boundary is accepted without
cross-domain substitution, and the next P8 wave may rely on the existing
domain-specific evidence contracts.
