# E2E Step 6 Schedule Contract Hardening Amendment v1.7

Status: APPLIED

Closes three E2E-12 interface/schema mismatches and four Platform Contract Gaps without changing Frozen Agent v2.1 or NSL v0.2 semantics.

- E2E12-P1-01 Scheduled WorkItem `source_type=SCHEDULE` / Occurrence provenance
- E2E12-P1-02 singular ScheduleTarget `required_capability` aligned with WC routing
- E2E12-P1-03 PA project binding enforced at ScheduleSpec/Target/WorkItem boundary
- E2E12-PCG-01 exactly-one atomic occurrence→WorkItem materialization
- E2E12-PCG-02 schedule update/disable/version fencing
- E2E12-PCG-03 deterministic CRON5/IANA/DST/fixed-interval/misfire time semantics
- E2E12-PCG-04 current-authorized typed Schedule API, durable audit and permanent E2E acceptance

Key invariant preserved:

`WC ScheduleSpec -> ScheduleOccurrence -> WorkItem -> successful WC Claim -> PA AgentExecution -> Result -> WA post-work projection`.
