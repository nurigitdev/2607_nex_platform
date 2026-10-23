# P8.7 Dual Approval Separation Closure v1.0

## 1. Status

```text
Status: CLOSED
Closure Slice: P8-S75
Closed At: 2026-10-23
```

This document records the P8.7 acceptance decision. It is additive evidence
for the frozen P8 design set and does not revise its authority documents.

## 2. Closed Boundary

The platform has one WC approval workbench but three non-substitutable approval
domains:

| Domain | Authority and SoR | Provider | Required protected lineage |
|---|---|---|---|
| `AGENT_FORMAL` | Agent Runtime | `AGENT` | exact agent action and execution |
| `NSL_WRITE` | NSL plus AE evidence store | `NSL` | ApprovalRequest, write intent, payload and NSL execution |
| `BUSINESS_FORMAL` | EOS plus WC decision store | `EOS` | ApprovalPolicy, ApprovalInstance, ApprovalStage and BusinessOperation |

WC is the common human-task projection and decision transport. It does not
convert evidence from one domain into authority for another domain.

## 3. Non-Substitution Decision

The following assertions are accepted and regression-protected:

```text
NSL_WRITE != BUSINESS_FORMAL != AGENT_FORMAL
NSL evidence does not satisfy BUSINESS_FORMAL
BUSINESS_FORMAL proof does not satisfy NSL_WRITE
AGENT_FORMAL evidence satisfies neither protected write boundary
```

EOS rejects a non-EOS provider, a non-`BUSINESS_FORMAL` domain, or lineage that
does not identify the exact EOS ApprovalStage. AE creates Platform
ApprovalEvidence only from an exact `NSL_WRITE` work item bound to the same
protected ApprovalRequest, runtime wait, payload and write intent. Rejection
occurs before mutation.

## 4. Actual PostgreSQL Acceptance

The protected P8-S75 pack connected to all four actual test databases:

| Service | Database | Owner |
|---|---|---|
| AE | `nex_ae_test` | `nex_ae_user` |
| WC | `nex_wc_test` | `nex_wc_user` |
| OA | `nex_oa_test` | `nex_oa_user` |
| EOS | `nex_eos_test` | `nex_eos_user` |

The pack verified current migrations and then exercised both approval paths:

1. AE/WC persisted and replayed the NSL request, human decision and Platform
   ApprovalEvidence.
2. WC performed a fresh OA authorization read at each of two formal approval
   stages.
3. EOS advanced the ordered stages and issued one immutable final
   ApprovalProof.
4. Restart read and exact replay returned the same terminal result.
5. Cross-domain substitutions failed closed, and smoke cleanup left zero
   residue.

Result: `8 passed`, zero skips.

## 5. Repository Acceptance

The Repository Full Gate completed successfully:

```text
pytest:              16,983 passed, 92 skipped
statement coverage:  96.78% (required 95%)
branch coverage:     96.21% (required 85%)
contracts:           188 schemas, 250 examples,
                     217 negative examples, 9 OpenAPI documents
AE Web:              359 passed, 0 failed, 0 skipped
process exit code:   0
```

The ordinary Full Gate retains protected smoke tests as explicit opt-in tests.
P8-S75 therefore ran the four-database protected pack separately and required
zero skips before admitting this closure.

## 6. Closure Decision

P8.7 is `CLOSED`.

- Fresh OA authority is preserved at every formal decision stage.
- Ordered multi-stage business approval remains EOS-owned.
- Final business ApprovalProof remains distinct from NSL WRITE evidence.
- WC may display all domains together without merging their state or authority.
- No migration, public API change or remote model provider was required for
  this acceptance Slice.

P8 may proceed beyond P8.7 using these domain-separation rules as a protected
baseline.
