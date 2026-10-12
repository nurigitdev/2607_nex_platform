# PLAT-CP03 v2.1 Contracts

These contracts replace Platform v2.0 embedded NSL invocation/idempotency/trust/result assumptions where they conflict with Frozen NSL v0.2.

Normative semantic authority remains the Frozen NSL v0.2 document set and Agent↔NSL Integration Contract v1.0.


## Step2 E2E Contract Hardening v1.3

- `SkillExecutionRequest v2.1` now requires `principal_context_ref` and `data_policy_ref`.
- The integration adapter resolves those refs deterministically into Frozen NSL `ExecutionRequest.principal` and `ExecutionRequest.data_policy`.
- Missing or unresolvable security references fail closed before RuntimeEngine invocation.


## Step 3 WRITE Contract Hardening v1.4
- SkillExecutionRequest RESUME requires resume_token_ref + approval_evidence_ref.
- Added typed ProtectedOperationDescriptor / OperationTrustDecision / GovernedWriteAuthorization.
- Added typed PackageTrustEvidence / ArtifactAdmissionDecision / VerifiedSkillArtifact.
- Governed write and package admission protocol types replace prior `Any` boundaries.
