#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

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
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.work_result_events import (
    SqlAlchemyWorkResultEventService,
)
from nex_runtime import load_env_file, redact_database_url
from nex_wc.coordination import (
    RoutingPolicy,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.work_results import (
    SqlAlchemyWorkResultRepository,
    WorkResultService,
)
from run_migrations import run_service_migrations
from sqlalchemy import text

SCHEMA_VERSION = "p7_s6_postgres_smoke.v1"
SMOKE_ENV = "NEX_P7_S6_POSTGRES_SMOKE"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
WC_DATABASE_ENV = "NEX_WC_TEST_DATABASE_URL"
RESULT_CONTRACT = "urn:nex:result:project-margin:1"
CAPABILITY = "FINANCE.PROJECT_MARGIN_READ"
PROFILE = "agent-profile://pa/project-margin-read/v1"


class _Candidates:
    def __init__(self, candidate: Mapping[str, object]) -> None:
        self._candidate = dict(candidate)

    def list_agents(self, **_kwargs):
        return [dict(self._candidate)]

    def get_agent(self, **_kwargs):
        return dict(self._candidate)


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:claim", "work:result:submit"],
            "revision_hash": "a" * 64,
        }


def run_p7_s6_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P7-S6",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
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
                continuation_verifier=_verify_work_result_resume,
            ),
        )
        checks = {
            "ae_migration_current": (
                "2404_ae_work_result_resume" in ae_migration.planned
                and len(ae_migration.planned)
                == len(ae_migration.applied) + len(ae_migration.skipped)
            ),
            "wc_migration_current": (
                "1002_wc_work_result" in wc_migration.planned
                and len(wc_migration.planned)
                == len(wc_migration.applied) + len(wc_migration.skipped)
            ),
            **dict(evidence.get("checks") or {}),
        }
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P7-S6",
                "profile": "test",
                "actual_postgres": True,
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
                "checks": checks,
            }
        )
        evidence["status"] = "PASS" if all(checks.values()) else "FAIL"
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected smoke boundary
        detail = p5_s5._redact_detail(str(exc), database_url=ae_url)
        detail = p5_s5._redact_detail(detail, database_url=wc_url)
        return _failure("execution_failed", detail)


def _verify_work_result_resume(fixture: Mapping[str, object]) -> dict[str, object]:
    ae_factory = fixture["factory"]
    wc_factory = fixture["wc_factory"]
    tenant_id = str(fixture["tenant_id"])
    parent = dict(fixture["execution"])
    now = str(fixture["now"])
    work_item_id = str(fixture["work_item_id"])
    wait_id = str(fixture["wait_id"])
    project_id = "project-p7-s5"
    agent_id = str(uuid4())
    child_execution_id = str(uuid4())
    trigger_id = str(uuid4())
    result_id = f"result-{uuid4()}"
    candidate = {
        "schema_version": "2.1",
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "agent_type": "PA",
        "profile_ref": PROFILE,
        "status": "ACTIVE",
        "project_id": project_id,
        "created_at": now,
        "version": 1,
    }
    identities = SqlAlchemyAgentIdentityRegistry(
        ae_factory, id_factory=lambda: agent_id
    )
    identities.register_agent(
        tenant_id=tenant_id,
        agent_type="PA",
        profile_ref=PROFILE,
        project_id=project_id,
    )
    coordination = WorkCoordinationService(
        SqlAlchemyCoordinationRepository(wc_factory),
        candidate_source=_Candidates(candidate),
        authorization_source=_Authorization(),
        policy=RoutingPolicy({CAPABILITY: (PROFILE,)}),
        clock=lambda: datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    coordination.route(
        tenant_id=tenant_id, work_item_id=work_item_id, expected_version=1
    )
    claimed = coordination.claim(
        tenant_id=tenant_id,
        work_item_id=work_item_id,
        expected_version=2,
    )
    with ae_factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO ae_agent_execution ("
                "tenant_id, agent_execution_id, agent_id, agent_type, principal_id, "
                "trigger_schema_version, trigger_id, source_type, source_ref, project_id, "
                "state, phase, version, correlation_id, causation_id, received_at, "
                "work_item_ref, claim_ref, claim_generation, assignment_ref, requester_ref, "
                "created_at, updated_at) VALUES ("
                ":tenant_id, :execution_id, :agent_id, 'PA', :principal_id, '2.1', "
                ":trigger_id, 'CLAIMED_WORKITEM', :work_item_id, :project_id, "
                "'RUNNING', 'RESULT_PUBLISH', 1, :correlation_id, :causation_id, :now, "
                ":work_item_id, :claim_id, :claim_generation, :assignment_id, "
                ":requester_ref, :now, :now)"
            ),
            {
                "tenant_id": tenant_id,
                "execution_id": child_execution_id,
                "agent_id": agent_id,
                "principal_id": parent["principal_id"],
                "trigger_id": trigger_id,
                "work_item_id": work_item_id,
                "project_id": project_id,
                "correlation_id": parent["correlation_id"],
                "causation_id": claimed["event_id"],
                "claim_id": claimed["claim"]["claim_id"],
                "claim_generation": claimed["claim"]["claim_generation"],
                "assignment_id": claimed["assignment"]["assignment_id"],
                "requester_ref": parent["principal_id"],
                "now": now,
            },
        )

    result_repository = SqlAlchemyWorkResultRepository(wc_factory)
    result_service = WorkResultService(
        result_repository,
        authorization_source=_Authorization(),
        clock=lambda: datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    work_result = {
        "schema_version": "2.1",
        "tenant_id": tenant_id,
        "result_id": result_id,
        "work_item_id": work_item_id,
        "revision_no": 1,
        "result_type": "PROJECT_MARGIN_ANALYSIS",
        "summary": "Reference-only S6 smoke result.",
        "payload": {"agent_result_ref": f"AE:AGENT_RESULT:{result_id}"},
        "schema_ref": RESULT_CONTRACT,
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "artifact_refs": [],
        "evidence_refs": [],
        "business_object_refs": [],
        "source_execution_ref": child_execution_id,
        "claim_ref": claimed["claim"]["claim_id"],
        "claim_generation": claimed["claim"]["claim_generation"],
        "assignment_ref": claimed["assignment"]["assignment_id"],
        "submitted_by": {"entity_type": "AGENT", "entity_id": agent_id},
        "trace": {"correlation_id": parent["correlation_id"]},
        "submitted_at": now,
    }
    accepted = result_service.submit(
        tenant_id=tenant_id,
        work_item_id=work_item_id,
        expected_version=int(claimed["work_item"]["version"]),
        work_result=work_result,
    )
    replayed = result_service.submit(
        tenant_id=tenant_id,
        work_item_id=work_item_id,
        expected_version=int(claimed["work_item"]["version"]),
        work_result=work_result,
    )
    event_row = result_repository.list_pending_result_events(limit=10)[0]
    delivery_job_id = str(uuid4())
    enqueued = result_repository.mark_result_event_enqueued(
        outbox_id=str(event_row["outbox_id"]),
        event_id=str(event_row["event_id"]),
        job_id=delivery_job_id,
        updated_at=now,
    )
    loaded_event = result_repository.load_result_event(
        outbox_id=str(event_row["outbox_id"]),
        event_id=str(event_row["event_id"]),
    )
    event_service = SqlAlchemyWorkResultEventService(
        ae_factory,
        runtime_jobs=SqlAlchemyRuntimeJobQueue(ae_factory),
        clock=lambda: datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    admitted = event_service.ingest(loaded_event["event_payload"])
    duplicate = event_service.ingest(loaded_event["event_payload"])
    delivered = result_repository.mark_result_event_delivered(
        outbox_id=str(event_row["outbox_id"]),
        event_id=str(event_row["event_id"]),
        job_id=delivery_job_id,
        updated_at=now,
    )
    with ae_factory() as session:
        ae_identity = tuple(
            session.execute(text("SELECT current_database(), current_user")).one()
        )
        wait = session.execute(
            text(
                "SELECT state, matched_event_id, resume_runtime_job_id "
                "FROM ae_wait_registration WHERE tenant_id = :tenant_id "
                "AND wait_id = :wait_id"
            ),
            {"tenant_id": tenant_id, "wait_id": wait_id},
        ).one()
        resume_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_runtime_job WHERE tenant_id = :tenant_id "
                    "AND job_type = 'RESUME_EXECUTION' AND wait_id = :wait_id"
                ),
                {"tenant_id": tenant_id, "wait_id": wait_id},
            ).scalar_one()
        )
    with wc_factory() as session:
        wc_identity = tuple(
            session.execute(text("SELECT current_database(), current_user")).one()
        )
        result_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM wc_work_result WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
    checks = {
        "ae_database_identity": ae_identity == ("nex_ae_test", "nex_ae_user"),
        "wc_database_identity": wc_identity == ("nex_wc_test", "nex_wc_user"),
        "wc_result_committed": accepted["created"] is True and result_count == 1,
        "wc_result_restart_idempotent": replayed["created"] is False
        and replayed["result_hash"] == accepted["result_hash"],
        "wc_result_outbox_delivered": enqueued["delivery_state"] == "ENQUEUED"
        and loaded_event["enqueued_job_id"] == delivery_job_id
        and delivered["delivery_state"] == "DELIVERED",
        "work_result_event_matched": admitted["inbox_state"] == "MATCHED",
        "wait_resume_queued": tuple(wait[:1]) == ("RESUME_QUEUED",),
        "event_lineage_retained": str(wait.matched_event_id)
        == str(event_row["event_id"]),
        "exactly_one_resume": resume_count == 1,
        "duplicate_event_idempotent": duplicate["created"] is False
        and duplicate["resume_runtime_job_id"] == admitted["resume_runtime_job_id"],
    }
    _cleanup_s6(
        ae_factory=ae_factory,
        wc_factory=wc_factory,
        tenant_id=tenant_id,
        child_execution_id=child_execution_id,
        agent_id=agent_id,
    )
    return {
        "checks": checks,
        "row_counts": {
            "wc_work_result": result_count,
            "ae_resume_runtime_job": resume_count,
            "ae_external_event_inbox": 1,
        },
    }


def _cleanup_s6(
    *, ae_factory, wc_factory, tenant_id: str, child_execution_id: str, agent_id: str
) -> None:
    with ae_factory.begin() as session:
        session.execute(
            text(
                "DELETE FROM ae_runtime_job WHERE tenant_id = :tenant_id "
                "AND job_type = 'RESUME_EXECUTION'"
            ),
            {"tenant_id": tenant_id},
        )
        session.execute(
            text("DELETE FROM ae_external_event_inbox WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        session.execute(
            text(
                "DELETE FROM ae_agent_execution WHERE tenant_id = :tenant_id "
                "AND agent_execution_id = :execution_id"
            ),
            {"tenant_id": tenant_id, "execution_id": child_execution_id},
        )
        session.execute(
            text(
                "DELETE FROM ae_agent_identity WHERE tenant_id = :tenant_id "
                "AND agent_id = :agent_id"
            ),
            {"tenant_id": tenant_id, "agent_id": agent_id},
        )
    with wc_factory.begin() as session:
        for table in (
            "wc_work_result",
            "wc_event_outbox",
            "wc_claim",
            "wc_assignment",
            "wc_routing_decision",
        ):
            session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )


def _target_allowed(database_url: str, *, user: str, database: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == user
        and unquote(parsed.path.lstrip("/")) == database
    )


def _failure(code: str, detail: str) -> dict[str, object]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P7-S6",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, object]) -> str:
    checks = dict(evidence.get("checks") or {})
    rows = dict(evidence.get("row_counts") or {})
    return (
        "p7_s6_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"work_results={rows.get('wc_work_result', 0)} "
        f"resume_jobs={rows.get('ae_resume_runtime_job', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p7_s6_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
