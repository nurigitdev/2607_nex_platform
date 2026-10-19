#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-wc",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s5_postgres_smoke as p5_s5
import run_p7_s5_postgres_smoke as p7_s5
import run_p7_s6_postgres_smoke as p7_s6
from nex_ae_api.agent_execution import (
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry
from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import (
    DelegateWorkExecutorDependencies,
    P5StepExecutionWorker,
    P5StepExecutorRegistry,
    P7DelegateWorkExecutor,
)
from nex_ae_api.work_result_events import (
    SqlAlchemyWorkResultEventService,
)
from nex_ae_api.work_result_resume import (
    SqlAlchemyWorkResultResumeSource,
)
from nex_runtime import (
    InMemoryJobQueue,
    load_env_file,
    redact_database_url,
)
from nex_wc.coordination import (
    RoutingPolicy,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.handoff_delivery import (
    HandoffDeliveryError,
    enqueue_pending_handoffs,
    run_handoff_delivery_job,
)
from nex_wc.work_items import (
    SqlAlchemyWorkItemRepository,
    WorkItemService,
)
from nex_wc.work_results import (
    SqlAlchemyWorkResultRepository,
    WorkResultService,
)
from run_migrations import run_service_migrations

SCHEMA_VERSION = "p7_s8_postgres_failure_smoke.v1"
SMOKE_ENV = "NEX_P7_S8_POSTGRES_FAILURE_SMOKE"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
WC_DATABASE_ENV = "NEX_WC_TEST_DATABASE_URL"
RESULT_CONTRACT = "urn:nex:result:project-margin:1"
CAPABILITY = "FINANCE.PROJECT_MARGIN_READ"
PROFILE = "agent-profile://pa/project-margin-read/v1"


class _CrashAfterStepCommitQueue:
    def __init__(self, queue: SqlAlchemyRuntimeJobQueue) -> None:
        self._queue = queue

    def complete(self, **_kwargs):
        raise RuntimeError("simulated process crash after StepResult commit")

    def fail(self, **kwargs):
        return self._queue.fail(**kwargs)


def run_p7_s8_postgres_failure_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P7-S8",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
            "actual_remote_provider": False,
        }
    ae_url = env.get(AE_DATABASE_ENV, "")
    wc_url = env.get(WC_DATABASE_ENV, "")
    if not _target_allowed(ae_url, user="nex_ae_user", database="nex_ae_test"):
        return _failure("target_not_allowed", "AE test database is required.")
    if not _target_allowed(wc_url, user="nex_wc_user", database="nex_wc_test"):
        return _failure("target_not_allowed", "WC test database is required.")
    try:
        ae_migration = run_service_migrations(
            "nex-ae-api", database_url=ae_url, profile="test"
        )
        wc_migration = run_service_migrations(
            "nex-wc", database_url=wc_url, profile="test"
        )
        evidence = p5_s5._execute_postgres_smoke(
            ae_url,
            verifier=lambda fixture: p7_s5._verify_delegate_wait(
                fixture,
                wc_url=wc_url,
                continuation_verifier=_verify_failure_recovery,
            ),
        )
        checks = {
            "ae_migration_current": len(ae_migration.planned)
            == len(ae_migration.applied) + len(ae_migration.skipped),
            "wc_migration_current": len(wc_migration.planned)
            == len(wc_migration.applied) + len(wc_migration.skipped),
            **dict(evidence.get("checks") or {}),
        }
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P7-S8",
                "profile": "test",
                "actual_postgres": True,
                "actual_remote_provider": False,
                "database_envs": [AE_DATABASE_ENV, WC_DATABASE_ENV],
                "redacted_database_urls": {
                    "ae": redact_database_url(ae_url),
                    "wc": redact_database_url(wc_url),
                },
                "migration": {
                    "ae_latest": ae_migration.planned[-1],
                    "ae_applied": len(ae_migration.applied),
                    "wc_latest": wc_migration.planned[-1],
                    "wc_applied": len(wc_migration.applied),
                },
                "failure_matrix": {
                    "claim_lease_expiry": "RECOVERED",
                    "stale_handoff": "REJECTED",
                    "handoff_ack_loss": "DEDUPLICATED",
                    "work_result_replay": "DEDUPLICATED",
                    "event_ack_loss": "DEDUPLICATED",
                    "resume_post_commit_crash": "LEASE_RECOVERED",
                },
                "checks": checks,
                "status": "PASS" if all(checks.values()) else "FAIL",
            }
        )
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected smoke boundary
        detail = p5_s5._redact_detail(str(exc), database_url=ae_url)
        detail = p5_s5._redact_detail(detail, database_url=wc_url)
        code = str(getattr(exc, "error_code", type(exc).__name__))
        return _failure("execution_failed", f"{code}: {detail}")


def _verify_failure_recovery(fixture: Mapping[str, object]) -> dict[str, object]:
    ae_factory = fixture["factory"]
    wc_factory = fixture["wc_factory"]
    tenant_id = str(fixture["tenant_id"])
    parent = dict(fixture["execution"])
    work_item_id = str(fixture["work_item_id"])
    wait_id = str(fixture["wait_id"])
    now = str(fixture["now"])
    clock = [datetime.fromisoformat(now.replace("Z", "+00:00"))]
    agent_id = str(uuid4())
    candidate = {
        "schema_version": "2.1",
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "agent_type": "PA",
        "profile_ref": PROFILE,
        "status": "ACTIVE",
        "project_id": "project-p7-s5",
        "created_at": now,
        "version": 1,
    }
    coordination_repository = SqlAlchemyCoordinationRepository(wc_factory)
    coordination = WorkCoordinationService(
        coordination_repository,
        candidate_source=p7_s6._Candidates(candidate),
        authorization_source=p7_s6._Authorization(),
        policy=RoutingPolicy({CAPABILITY: (PROFILE,)}),
        clock=lambda: clock[0],
        lease_seconds=30,
    )
    coordination.route(
        tenant_id=tenant_id, work_item_id=work_item_id, expected_version=1
    )
    first_claim = coordination.claim(
        tenant_id=tenant_id, work_item_id=work_item_id, expected_version=2
    )
    delivery_queue = InMemoryJobQueue()
    stale_job = enqueue_pending_handoffs(
        store=coordination_repository,
        queue=delivery_queue,
        clock=lambda: clock[0],
    )[0]
    clock[0] += timedelta(seconds=31)
    second_claim = coordination.claim(
        tenant_id=tenant_id, work_item_id=work_item_id, expected_version=3
    )
    stale_delivery_calls: list[object] = []
    stale_error = None
    try:
        run_handoff_delivery_job(
            stale_job,
            store=coordination_repository,
            client=SimpleNamespace(
                deliver=lambda envelope: stale_delivery_calls.append(envelope) or {}
            ),
            clock=lambda: clock[0],
        )
    except HandoffDeliveryError as exc:
        stale_error = exc.error_code

    identities = SqlAlchemyAgentIdentityRegistry(
        ae_factory, id_factory=lambda: agent_id, clock=lambda: clock[0]
    )
    identities.register_agent(
        tenant_id=tenant_id,
        agent_type="PA",
        profile_ref=PROFILE,
        project_id="project-p7-s5",
    )
    admission = AgentExecutionAdmissionService(
        identities=identities,
        executions=SqlAlchemyAgentExecutionRepository(ae_factory),
        mode="required",
        clock=lambda: clock[0],
    )
    admitted_handoff = admission.admit_claimed_work(
        event_id=str(second_claim["event_id"]),
        requester_ref=str(parent["principal_id"]),
        handoff=second_claim["handoff"],
        planning_source=second_claim["planning_source"],
    )
    replayed_handoff = admission.admit_claimed_work(
        event_id=str(second_claim["event_id"]),
        requester_ref=str(parent["principal_id"]),
        handoff=second_claim["handoff"],
        planning_source=second_claim["planning_source"],
    )
    if admitted_handoff.execution is None or replayed_handoff.execution is None:
        raise RuntimeError("P7-S8 current claim handoff was not admitted")
    child_execution_id = str(admitted_handoff.execution["agent_execution_id"])

    items = WorkItemService(SqlAlchemyWorkItemRepository(wc_factory))
    result_repository = SqlAlchemyWorkResultRepository(wc_factory)
    results = WorkResultService(
        result_repository,
        authorization_source=p7_s6._Authorization(),
        clock=lambda: clock[0],
    )
    result_id = f"result-{uuid4()}"
    status = items.status(tenant_id=tenant_id, work_item_id=work_item_id)
    work_result = {
        "schema_version": "2.1",
        "tenant_id": tenant_id,
        "result_id": result_id,
        "work_item_id": work_item_id,
        "revision_no": 1,
        "result_type": "PROJECT_MARGIN_ANALYSIS",
        "summary": "Reference-only P7-S8 restart recovery result.",
        "payload": {"agent_result_ref": f"AE:AGENT_RESULT:{result_id}"},
        "schema_ref": RESULT_CONTRACT,
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "artifact_refs": [],
        "evidence_refs": [],
        "business_object_refs": [],
        "source_execution_ref": child_execution_id,
        "claim_ref": second_claim["claim"]["claim_id"],
        "claim_generation": second_claim["claim"]["claim_generation"],
        "assignment_ref": second_claim["assignment"]["assignment_id"],
        "submitted_by": {"entity_type": "AGENT", "entity_id": agent_id},
        "trace": {"correlation_id": parent["correlation_id"]},
        "submitted_at": _time(clock[0]),
    }
    accepted = results.submit(
        tenant_id=tenant_id,
        work_item_id=work_item_id,
        expected_version=int(status["version"]),
        work_result=work_result,
    )
    replayed = results.submit(
        tenant_id=tenant_id,
        work_item_id=work_item_id,
        expected_version=int(status["version"]),
        work_result=work_result,
    )
    event_row = next(
        row
        for row in result_repository.list_pending_result_events(limit=100)
        if row["event_payload"]["tenant_id"] == tenant_id
        and row["event_payload"]["work_item_id"] == work_item_id
    )
    delivery_job_id = str(uuid4())
    result_repository.mark_result_event_enqueued(
        outbox_id=str(event_row["outbox_id"]),
        event_id=str(event_row["event_id"]),
        job_id=delivery_job_id,
        updated_at=_time(clock[0]),
    )
    loaded = result_repository.load_result_event(
        outbox_id=str(event_row["outbox_id"]), event_id=str(event_row["event_id"])
    )
    runtime_jobs = SqlAlchemyRuntimeJobQueue(ae_factory)
    event_service = SqlAlchemyWorkResultEventService(
        ae_factory, runtime_jobs=runtime_jobs, clock=lambda: clock[0]
    )
    admitted = event_service.ingest(loaded["event_payload"])
    duplicate = event_service.ingest(loaded["event_payload"])
    result_repository.mark_result_event_delivered(
        outbox_id=str(event_row["outbox_id"]),
        event_id=str(event_row["event_id"]),
        job_id=delivery_job_id,
        updated_at=_time(clock[0]),
    )

    resume_claim = runtime_jobs.claim(
        tenant_id=tenant_id,
        worker_id="p7-s8-resume-worker",
        lease_seconds=60,
        now=_time(clock[0]),
    )
    if resume_claim is None or resume_claim.job["job_type"] != "RESUME_EXECUTION":
        raise RuntimeError("P7-S8 RESUME_EXECUTION job was not claimable")
    dependencies = DelegateWorkExecutorDependencies(
        runtime_repository=SimpleNamespace(load=lambda **_kwargs: {}),
        wait_repository=SimpleNamespace(register=lambda **_kwargs: {}),
        work_item_client=SimpleNamespace(create_work_item=lambda _payload: {}),
    )
    worker_args = {
        "engine": SqlAlchemyMultiStepEngine(ae_factory, runtime_jobs),
        "executors": P5StepExecutorRegistry(
            {"WC_DELEGATE_WORK": P7DelegateWorkExecutor(dependencies=dependencies)}
        ),
        "continuation_source": SqlAlchemyWorkResultResumeSource(ae_factory),
    }
    crashed_after_commit = False
    try:
        P5StepExecutionWorker(
            **worker_args,
            jobs=_CrashAfterStepCommitQueue(runtime_jobs),
            clock=lambda: clock[0],
        ).run_claim(tenant_id=tenant_id, claim=resume_claim)
    except RuntimeError as exc:
        crashed_after_commit = "simulated process crash" in str(exc)

    clock[0] += timedelta(seconds=61)
    recovered_claim = runtime_jobs.claim(
        tenant_id=tenant_id,
        worker_id="p7-s8-restarted-worker",
        lease_seconds=60,
        now=_time(clock[0]),
    )
    if recovered_claim is None:
        raise RuntimeError("P7-S8 expired RESUME_EXECUTION lease was not recoverable")
    recovered = P5StepExecutionWorker(
        **worker_args, jobs=runtime_jobs, clock=lambda: clock[0]
    ).run_claim(tenant_id=tenant_id, claim=recovered_claim)

    with ae_factory() as session:
        ae_identity = tuple(
            session.execute(text("SELECT current_database(), current_user")).one()
        )
        wait_state = session.execute(
            text(
                "SELECT state FROM ae_wait_registration WHERE tenant_id = :tenant_id "
                "AND wait_id = :wait_id"
            ),
            {"tenant_id": tenant_id, "wait_id": wait_id},
        ).scalar_one()
        step_result_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_step_result WHERE tenant_id = :tenant_id "
                    "AND executable_step_id = :step_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "step_id": resume_claim.job["executable_step_id"],
                },
            ).scalar_one()
        )
        resume_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_runtime_job WHERE tenant_id = :tenant_id "
                    "AND job_type = 'RESUME_EXECUTION' AND wait_id = :wait_id"
                ),
                {"tenant_id": tenant_id, "wait_id": wait_id},
            ).scalar_one()
        )
        inbox_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_external_event_inbox "
                    "WHERE tenant_id = :tenant_id AND event_id = :event_id"
                ),
                {"tenant_id": tenant_id, "event_id": event_row["event_id"]},
            ).scalar_one()
        )
    with wc_factory() as session:
        wc_identity = tuple(
            session.execute(text("SELECT current_database(), current_user")).one()
        )
        claim_rows = session.execute(
            text(
                "SELECT claim_generation, state FROM wc_claim "
                "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id "
                "ORDER BY claim_generation"
            ),
            {"tenant_id": tenant_id, "work_item_id": work_item_id},
        ).all()
        old_outbox_state = session.execute(
            text(
                "SELECT delivery_state FROM wc_event_outbox "
                "WHERE tenant_id = :tenant_id AND outbox_id = :outbox_id"
            ),
            {"tenant_id": tenant_id, "outbox_id": first_claim["outbox_id"]},
        ).scalar_one()
        result_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM wc_work_result WHERE tenant_id = :tenant_id "
                    "AND work_item_id = :work_item_id"
                ),
                {"tenant_id": tenant_id, "work_item_id": work_item_id},
            ).scalar_one()
        )
    attempts = runtime_jobs.list_attempts(
        tenant_id, str(resume_claim.job["runtime_job_id"])
    )
    checks = {
        "ae_database_identity": ae_identity == ("nex_ae_test", "nex_ae_user"),
        "wc_database_identity": wc_identity == ("nex_wc_test", "nex_wc_user"),
        "expired_claim_reclaimed_once": [tuple(row) for row in claim_rows]
        == [(1, "EXPIRED"), (2, "ACTIVE")],
        "stale_handoff_failed_closed": stale_error == "wc.handoff_claim_stale"
        and not stale_delivery_calls
        and old_outbox_state == "FAILED",
        "current_handoff_restart_idempotent": child_execution_id
        == str(replayed_handoff.execution["agent_execution_id"]),
        "work_result_restart_idempotent": accepted["created"] is True
        and replayed["created"] is False
        and result_count == 1,
        "result_event_ack_loss_idempotent": admitted["created"] is True
        and duplicate["created"] is False
        and inbox_count == 1
        and resume_count == 1,
        "resume_crash_recovered": crashed_after_commit
        and recovered.disposition == "ALREADY_TERMINAL"
        and recovered.runtime_job["state"] == "DONE",
        "resume_exactly_once_semantics": step_result_count == 1
        and wait_state == "CONSUMED"
        and [attempt["outcome"] for attempt in attempts]
        == ["LEASE_EXPIRED", "DONE"],
    }
    return {
        "checks": checks,
        "row_counts": {
            "wc_claim": len(claim_rows),
            "wc_work_result": result_count,
            "ae_external_event_inbox": inbox_count,
            "ae_resume_runtime_job": resume_count,
            "ae_parent_step_result": step_result_count,
            "ae_resume_attempt": len(attempts),
        },
        "failure_matrix": {
            "claim_lease_expiry": "RECOVERED",
            "stale_handoff": "REJECTED",
            "work_result_replay": "DEDUPLICATED",
            "event_ack_loss": "DEDUPLICATED",
            "resume_post_commit_crash": "LEASE_RECOVERED",
        },
    }


def _target_allowed(database_url: str, *, user: str, database: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == user
        and unquote(parsed.path.lstrip("/")) == database
    )


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _failure(code: str, detail: str) -> dict[str, object]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P7-S8",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "actual_remote_provider": False,
    }


def summary_line(evidence: Mapping[str, object]) -> str:
    checks = dict(evidence.get("checks") or {})
    rows = dict(evidence.get("row_counts") or {})
    return (
        "p7_s8_postgres_failure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"claims={rows.get('wc_claim', 0)} "
        f"resume_attempts={rows.get('ae_resume_attempt', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p7_s8_postgres_failure_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
