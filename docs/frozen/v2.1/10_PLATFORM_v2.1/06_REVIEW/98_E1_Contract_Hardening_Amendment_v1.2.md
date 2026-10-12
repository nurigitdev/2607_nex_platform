# E1 Contract Hardening Amendment v1.2

**Status:** CONTROLLED CONTRACT HARDENING — APPLIED

This amendment closes the four PASS E1 findings without changing Frozen Agent v2.1 or NSL v0.2 semantics.

Closed:
- E2E-P1-01 PA project_id nullability
- E2E-P1-02 WC AGENT candidate discriminator
- E2E-PCG-01 WC Claim → AE CLAIMED_WORKITEM exact machine-readable bridge
- E2E-PCG-02 one ACTIVE PA per tenant/project enforcement

Normative changes:
- AgentIdentity v2.1 conditional schema tightened.
- RoutingDecision v2.1 conditional schema tightened.
- Added ExecutionTrigger v2.1 and ClaimExecutionHandoff v2.1.
- Added AE Agent Registry persistence/service contract.
- Back-propagated exact requirements to 04 / 14 / 15 / 29.
