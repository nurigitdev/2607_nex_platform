# PLAT-CP04 Approval Contracts

Normative Platform v2.1 integration contracts introduced by CP04.

- `approval-work-item-v1.schema.json`: WC human approval workflow state.
- `nsl-write-approval-request-v2.1.schema.json`: NSL-owned exact WRITE approval request binding.
- `agent-formal-approval-request-v2.1.schema.json`: Agent business/process formal approval request.
- `approval-decision-v2.1.schema.json`: human decision accepted only after current OA authorization.
- `human-gate-view-v2.1.schema.json`: AE-WEB / IA presentation projection.
- `approval_protocols_v2_1.py`: provider-agnostic workflow and EOS business approval adapter seams.

Key invariant:
`Human Confirmation != Agent FORMAL_APPROVAL != NSL WRITE Approval != OA Step-up`.


## Step 3 WRITE Contract Hardening v1.4
- ApprovalWorkItem has domain-specific required bindings for AGENT_FORMAL and NSL_WRITE.
- ApprovalDecision requires a non-null OA decision reference.
- `approval-evidence-v2.1` and `nsl-approval-resume-v2.1` are canonical machine-readable NSL suspend/resume bridge contracts.
