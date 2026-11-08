# NeX Platform v2.1 E2E Step 6
# Scheduled PA Recurring Work Contract Hardening Closure & Re-validation v1.1

**Status:** CLOSED / PASS  
**Baseline:** Platform v2.1 v1.7 + Frozen Agent v2.1 + Frozen NSL v0.2  
**Scope:** E2E-12 Scheduled PA Recurring Work

---

# 1. Executive Result

```text
E2E-12 Scheduled PA Recurring Work  PASS

E2E-P0  = 0
E2E-P1  = 0
E2E-PCG = 0
```

> **Integrated E2E Step 6 — CLOSED / PASS**

# 2. Seven Findings Closed

## E2E12-P1-01 Scheduled WorkItem provenance

Canonical WorkItem accepts `source_type=SCHEDULE`; scheduled materialization requires `source_ref=OccurrenceId`.

## E2E12-P1-02 Capability cardinality

ScheduleTarget uses one `required_capability`, identical to WC WorkItem/RoutingDecision semantics.

## E2E12-P1-03 PA project binding

PA Schedule requires project_id/project_scope and the generated WorkItem preserves the same project reference/scope. Mismatch fails closed.

## E2E12-PCG-01 Exactly-one materialization

Occurrence→WorkItem is a single WC transaction boundary. `wc_schedule_materialization` provides occurrence/materialization uniqueness plus payload-hash replay/conflict semantics.

## E2E12-PCG-02 Version / enable fencing

ScheduleOccurrence snapshots `schedule_version`; materialization locks current ScheduleSpec and requires enabled=true and current version==expected version before WorkItem creation.

## E2E12-PCG-03 Deterministic time / misfire

`WC_SCHEDULE_TIME_V1` fixes CRON5, IANA timezone, DST gap/overlap policy, UTC nominal instants and canonical fixed intervals. SKIP/CATCH_UP/LATEST_ONLY are applied to that deterministic nominal instant set.

## E2E12-PCG-04 OA / API / Audit / Acceptance

Schedule API is typed and current-authorized. Scheduler materialization uses service authorization evidence. Durable audit captures actor/service, authorization decision, correlation and schedule/occurrence/work item refs. TST-E12-01~10 are permanent acceptance cases.

# 3. Canonical E2E-12 Chain

```text
Project / PA
→ WC ScheduleSpec
→ WC Durable Scheduler
→ version-bound ScheduleOccurrence
→ current enabled/version/authority fence
→ atomic exactly-one WorkItem materialization
→ PA eligibility
→ Atomic Claim
→ CLAIMED_WORKITEM
→ PA AgentExecution
→ Result
→ WA post-work projection
```

Hard invariants:

```text
WA != Scheduler
PA has no in-process timer
Schedule/Occurrence -> direct AgentExecution = 0
same occurrence + same payload -> same WorkItem
different payload under same materialization identity -> MATERIALIZATION_CONFLICT
stale/disabled schedule -> WorkItem = 0
AgentExecution begins only after successful Claim
```

# 4. Verdict

> **E2E Step 6 Scheduled PA Recurring Work — CLOSED / PASS**

Next planned validation: `Fault Variants FV-01 ~ FV-10`.

# 5. Re-validation Evidence

```text
E2E-12 contract probes           : 44 / 44 PASS
Normative JSON Schema structure  : 61 / 61 PASS
Normative Python protocol compile: 12 / 12 PASS
Changed DOCX render/diff QA      : 13 / 13 PASS
Frozen Agent / NSL semantics     : UNCHANGED
Step 4 WRITE reliability         : UNCHANGED
Step 5 Result Publication        : UNCHANGED
```

This closure is an Architecture/Contract E2E consistency result. It is not a live source-code runtime or performance-test result.
