# NeX Platform v2.1 Working Set v1.7 — E2E Step 6 Closure

Status: E2E-12 CLOSED / PASS

Baseline delta from v1.6:
- Added Scheduled WorkItem `source_type=SCHEDULE` provenance and OccurrenceId source binding.
- Aligned ScheduleTarget with WC singular `required_capability` semantics.
- Enforced PA Schedule project binding through ScheduleSpec/Target/WorkItem lineage.
- Added schedule-version/enabled fencing and atomic exactly-one occurrence→WorkItem materialization with payload-hash conflict detection.
- Fixed deterministic `WC_SCHEDULE_TIME_V1` semantics: CRON5, IANA timezone, DST gap/overlap rules, UTC nominal instants, canonical fixed intervals and deterministic misfire.
- Hardened typed Schedule API, current authorization context and durable schedule audit evidence.
- Added permanent E2E-12 acceptance for duplicate scanner, misfire, disable/update race, tenant/project mismatch, claim race and WA projection-only boundary.

Frozen Agent v2.1 / NSL v0.2 normative baseline files were not modified.

Next validation: Fault Variants FV-01 ~ FV-10.
