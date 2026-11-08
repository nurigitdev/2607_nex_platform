# PLAT-CP05 / E2E-12 WC Recurring Work / Schedule Contracts v1.1

Canonical Platform v2.1 rules:

- ScheduleSpec and ScheduleOccurrence are owned by NeX-WC.
- A ScheduleOccurrence never creates AgentExecution directly.
- It materializes exactly one semantic WC WorkItem idempotently, then Agent execution begins only after a successful WC atomic Claim and CLAIMED_WORKITEM trigger.
- Scheduled WorkItem provenance is `source.source_type=SCHEDULE` and `source.source_ref=occurrence_id`.
- ScheduleTarget uses one canonical `required_capability`, matching WC WorkItem/RoutingDecision semantics.
- PA schedule requires `ScheduleSpec.project_id == ScheduleTarget.project_scope_ref` and the same project binding in the generated WorkItem.
- Materialization is one WC transaction boundary with schedule-version/enabled fencing, occurrence/materialization uniqueness, payload-hash conflict detection, WorkItem creation, and occurrence MATERIALIZED commit.
- PA may manage project-owned schedule policy through current-authorized WC APIs but does not hold an in-process timer.
- `WC_SCHEDULE_TIME_V1`: CRON5/IANA TZDB, deterministic DST gap/overlap rules, UTC nominal instants; FIXED_INTERVAL uses canonical instant-based ISO8601 intervals.
- Misfire applies deterministically to nominal UTC instants: SKIP / bounded CATCH_UP / LATEST_ONLY.
- Schedule CRUD/query and service materialization create durable audit evidence with current authorization decision references.
- NeX-WA remains Work Asset / post-work projection and never becomes Schedule SoR.
- Runtime JobQueue `available_at`/retry scheduling is an implementation/reliability mechanism, not the Business Schedule definition.
