# NeX Platform v2.1 E2E Step 6 Schedule Hardening v1.7

This Controlled Amendment closes E2E-12 Scheduled PA Recurring Work gaps without changing Frozen Agent v2.1 or NSL v0.2 semantics.

Closed contract areas:
- Scheduled WorkItem source/provenance and singular capability semantics.
- PA project binding from ScheduleSpec/Target through WorkItem/Claim.
- Exactly-one occurrence→WorkItem materialization with payload-hash conflict detection.
- Schedule version/enabled fencing before materialization.
- Deterministic CRON5/IANA timezone/DST/fixed-interval/misfire semantics.
- Current-authorized Schedule API and durable security/audit evidence.
- E2E-12 permanent acceptance coverage including duplicate scanner, misfire, disable/update race, tenant/project mismatch, claim race, and WA projection-only checks.

Invariant: `ScheduleOccurrence -> WorkItem -> successful Claim -> PA AgentExecution`; neither Schedule nor WA may directly start AgentExecution.
