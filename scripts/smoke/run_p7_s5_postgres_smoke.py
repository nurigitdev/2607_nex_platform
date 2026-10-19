#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

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
from nex_ae_api.delegated_work import (
    DelegatedWorkError,
    SqlAlchemyDelegationRuntimeRepository,
    SqlAlchemyWaitRegistrationRepository,
)
from nex_ae_api.executable_plans import (
    WC_DELEGATE_WORK_EXECUTOR_KIND,
    executable_plan_semantic_projection,
)
from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import (
    DelegateWorkExecutorDependencies,
    P5StepExecutionWorker,
    P5StepExecutorRegistry,
    P7DelegateWorkExecutor,
)
from nex_runtime import load_env_file, redact_database_url, sqlalchemy_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.work_items import (
    SqlAlchemyWorkItemRepository,
    WorkItemError,
    WorkItemService,
)
from run_migrations import run_service_migrations

SCHEMA_VERSION = "p7_s5_postgres_smoke.v1"
SMOKE_ENV = "NEX_P7_S5_POSTGRES_SMOKE"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
WC_DATABASE_ENV = "NEX_WC_TEST_DATABASE_URL"


class _DirectWorkItemClient:
    def __init__(self, service: WorkItemService) -> None:
        self._service = service

    def create_work_item(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            return self._service.create(payload)
        except WorkItemError as exc:
            raise DelegatedWorkError(
                exc.error_code,
                exc.detail,
                exc.retryable,
            ) from exc


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate"],
            "revision_hash": "a" * 64,
        }


def run_p7_s5_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P7-S5",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    ae_url = env.get(AE_DATABASE_ENV, "")
    wc_url = env.get(WC_DATABASE_ENV, "")
    if not p5_s5._target_url_allowed(ae_url) or not _wc_target_allowed(wc_url):
        return _failure("target_not_allowed", "AE and WC test databases are required.")
    try:
        ae_migration = run_service_migrations(
            "nex-ae-api", database_url=ae_url, profile="test"
        )
        wc_migration = run_service_migrations(
            "nex-wc", database_url=wc_url, profile="test"
        )
        evidence = p5_s5._execute_postgres_smoke(
            ae_url,
            verifier=lambda fixture: _verify_delegate_wait(fixture, wc_url=wc_url),
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P7-S5",
                "profile": "test",
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
            }
        )
        evidence["checks"] = {
            "ae_migration_current": ae_migration.planned[-1]
            == "2403_ae_delegate_work_activation",
            "wc_migration_current": wc_migration.planned[-1]
            == "1003_wc_work_item_authorization",
            **evidence["checks"],
        }
        evidence["status"] = "PASS" if all(evidence["checks"].values()) else "FAIL"
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected smoke boundary
        detail = p5_s5._redact_detail(str(exc), database_url=ae_url)
        detail = p5_s5._redact_detail(detail, database_url=wc_url)
        return _failure("execution_failed", detail)


def _verify_delegate_wait(
    fixture: Mapping[str, Any],
    *,
    wc_url: str,
    continuation_verifier=None,
    delegation_overrides: Mapping[str, Any] | None = None,
    authorization_source=None,
    expect_authorization_denied: bool = False,
) -> dict[str, Any]:
    ae_factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    execution = dict(fixture["execution"])
    plan = json.loads(json.dumps(fixture["executable_plan"]))
    now = str(fixture["now"])
    step = plan["steps"][0]
    delegation_id = str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/ae/delegations/"
            f"{execution['agent_execution_id']}/1/{step['logical_step_ref']}",
        )
    )
    delegation = {
        "schema_version": "1.0",
        "delegation_id": delegation_id,
        "delegation_revision": 1,
        "goal": "Verify P7 delegated project analysis.",
        "work_class": "ANALYSIS",
        "required_agent_type": "PA",
        "required_capability": "FINANCE.PROJECT_MARGIN_READ",
        "project_ref": {"entity_type": "PROJECT", "entity_id": "project-p7-s5"},
        "project_scope_ref": "project-p7-s5",
        "result_contract_ref": "urn:nex:result:project-margin:1",
        "completion_policy": "OWNER_SUBMITS",
    }
    if delegation_overrides:
        delegation.update(dict(delegation_overrides))
    step.update(
        {
            "step_type": "DELEGATE_WORK",
            "executor_kind": WC_DELEGATE_WORK_EXECUTOR_KIND,
            "required_capability": delegation["required_capability"],
            "capability_version": "delegation.v1",
            "output_contract_ref": delegation["result_contract_ref"],
            "delegation": delegation,
            "timeout_policy_ref": "policy://nex/ae/wc-delegate-timeout/v1",
            "retry_policy_ref": "policy://nex/ae/wc-delegate-retry/v1",
        }
    )
    plan["schema_version"] = "1.3"
    plan["compiler_version"] = "p7.1"
    step["step_contract_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in step.items()
            if key not in {"executable_step_id", "step_contract_hash"}
        }
    )
    plan["executable_plan_hash"] = semantic_sha256_hash_ref(
        executable_plan_semantic_projection(plan)
    )
    with ae_factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_plan SET plan_json = CAST(:plan_json AS jsonb), "
                "compiler_version = 'p7.1', plan_hash = :plan_hash "
                "WHERE tenant_id = :tenant_id "
                "AND executable_plan_id = :plan_id"
            ),
            {
                "plan_json": json.dumps(plan, sort_keys=True),
                "plan_hash": plan["executable_plan_hash"],
                "tenant_id": tenant_id,
                "plan_id": plan["executable_plan_id"],
            },
        )
        session.execute(
            text(
                "UPDATE ae_executable_step SET step_kind = 'WC_DELEGATE_WORK', "
                "step_type = 'DELEGATE_WORK', executor_kind = 'WC_DELEGATE_WORK', "
                "required_capability = :capability, capability_version = 'delegation.v1', "
                "output_contract_ref = :contract_ref, step_contract_hash = :step_hash "
                "WHERE tenant_id = :tenant_id "
                "AND executable_step_id = :step_id"
            ),
            {
                "capability": delegation["required_capability"],
                "contract_ref": delegation["result_contract_ref"],
                "step_hash": step["step_contract_hash"],
                "tenant_id": tenant_id,
                "step_id": step["executable_step_id"],
            },
        )

    wc_engine = create_engine(
        sqlalchemy_database_url(wc_url), future=True, pool_pre_ping=True
    )
    wc_factory = sessionmaker(bind=wc_engine, autoflush=False, expire_on_commit=False)
    verification: dict[str, Any] | None = None
    cleanup_counts: dict[str, int] = {}
    try:
        work_items = WorkItemService(
            SqlAlchemyWorkItemRepository(wc_factory),
            authorization_source=authorization_source or _Authorization(),
        )
        queue = SqlAlchemyRuntimeJobQueue(ae_factory)
        engine = SqlAlchemyMultiStepEngine(ae_factory, queue)
        executor = P7DelegateWorkExecutor(
            dependencies=DelegateWorkExecutorDependencies(
                runtime_repository=SqlAlchemyDelegationRuntimeRepository(ae_factory),
                wait_repository=SqlAlchemyWaitRegistrationRepository(ae_factory),
                work_item_client=_DirectWorkItemClient(work_items),
            ),
            clock=lambda: datetime.fromisoformat(now.replace("Z", "+00:00")),
        )
        worker = P5StepExecutionWorker(
            engine=engine,
            jobs=queue,
            executors=P5StepExecutorRegistry(
                {WC_DELEGATE_WORK_EXECUTOR_KIND: executor}
            ),
            clock=lambda: datetime.fromisoformat(now.replace("Z", "+00:00")),
        )
        engine.schedule_next(
            tenant_id=tenant_id,
            execution_id=execution["agent_execution_id"],
            now=now,
        )
        claim = queue.claim(
            tenant_id=tenant_id,
            worker_id="p7-s5-worker",
            lease_seconds=60,
            now=now,
        )
        if claim is None:
            raise RuntimeError("P7-S5 RuntimeJob was not claimable")
        result = worker.run_claim(tenant_id=tenant_id, claim=claim)
        if expect_authorization_denied:
            verification = _authorization_denied_evidence(
                ae_factory=ae_factory,
                wc_factory=wc_factory,
                tenant_id=tenant_id,
                parent_execution_id=str(execution["agent_execution_id"]),
                result=result,
                cleanup_counts=cleanup_counts,
            )
            return verification
        with ae_factory() as session:
            parent = session.execute(
                text(
                    "SELECT state, phase FROM ae_agent_execution "
                    "WHERE tenant_id = :tenant_id "
                    "AND agent_execution_id = :execution_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": execution["agent_execution_id"],
                },
            ).one()
            wait = session.execute(
                text(
                    "SELECT wait_id, external_ref, state FROM ae_wait_registration "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).one()
        with wc_factory() as session:
            wc_identity = session.execute(
                text("SELECT current_database(), current_user")
            ).one()
            work_ids = (
                session.execute(
                    text(
                        "SELECT work_item_id FROM wc_work_item "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                )
                .scalars()
                .all()
            )
            work_count = len(work_ids)
        checks = {
            "delegate_worker_waited": result.disposition == "WAITING"
            and result.step_result is None,
            "wait_persisted_before_completion": wait.state == "PENDING",
            "stable_external_identity": len(work_ids) == 1
            and str(wait.external_ref) == str(work_ids[0]),
            "parent_waiting_dependency": tuple(parent)
            == ("WAITING_DEPENDENCY", "STEP_EXECUTION"),
            "wc_work_item_created_once": work_count == 1,
            "wc_database_identity": tuple(wc_identity)
            == ("nex_wc_test", "nex_wc_user"),
        }
        checks["delegate_worker_waited"] = checks["delegate_worker_waited"] and (
            result.step["state"] == "WAITING" and result.runtime_job["state"] == "DONE"
        )
        continuation = (
            {}
            if continuation_verifier is None
            else dict(
                continuation_verifier(
                    {
                        **dict(fixture),
                        "wc_factory": wc_factory,
                        "work_item_id": str(wait.external_ref),
                        "wait_id": str(wait.wait_id),
                    }
                )
            )
        )
        verification = {
            "checks": {**checks, **dict(continuation.get("checks") or {})},
            "row_counts": {
                "wait_registration": 1,
                "wc_work_item": work_count,
                **dict(continuation.get("row_counts") or {}),
            },
            "cleanup_counts": cleanup_counts,
        }
    finally:
        cleanup_counts.update(
            _cleanup_delegate_runtime_rows(ae_factory, tenant_id=tenant_id)
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
            cleanup_counts["wc_work_item"] = int(
                session.execute(
                    text("DELETE FROM wc_work_item WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
            cleanup_counts["wc_remaining"] = sum(
                int(
                    session.execute(
                        text(
                            f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"
                        ),
                        {"tenant_id": tenant_id},
                    ).scalar_one()
                )
                for table in (
                    "wc_work_result",
                    "wc_event_outbox",
                    "wc_claim",
                    "wc_assignment",
                    "wc_routing_decision",
                    "wc_work_item",
                )
            )
        wc_engine.dispose()
        if verification is not None:
            verification["checks"]["delegate_runtime_cleanup_complete"] = (
                cleanup_counts["delegate_runtime_remaining"] == 0
                and cleanup_counts["wc_remaining"] == 0
            )
    if verification is None:
        raise RuntimeError("P7-S5 verification did not produce evidence")
    verification["checks"]["delegate_runtime_cleanup_complete"] = (
        cleanup_counts["delegate_runtime_remaining"] == 0
        and cleanup_counts["wc_remaining"] == 0
    )
    return verification


def _authorization_denied_evidence(
    *,
    ae_factory,
    wc_factory,
    tenant_id: str,
    parent_execution_id: str,
    result,
    cleanup_counts: dict[str, int],
) -> dict[str, Any]:
    with wc_factory() as session:
        wc_identity = tuple(
            session.execute(text("SELECT current_database(), current_user")).one()
        )
        wc_counts = {
            table: int(
                session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in (
                "wc_work_item",
                "wc_assignment",
                "wc_claim",
                "wc_event_outbox",
            )
        }
        handoff_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM wc_event_outbox "
                    "WHERE tenant_id = :tenant_id "
                    "AND event_type = 'CLAIM_EXECUTION_HANDOFF'"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
    with ae_factory() as session:
        child_execution_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_agent_execution "
                    "WHERE tenant_id = :tenant_id "
                    "AND source_type = 'CLAIMED_WORKITEM'"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
        child_runtime_job_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_runtime_job AS job "
                    "JOIN ae_agent_execution AS execution "
                    "ON execution.tenant_id = job.tenant_id "
                    "AND CAST(execution.agent_execution_id AS TEXT) = job.execution_id "
                    "WHERE job.tenant_id = :tenant_id "
                    "AND execution.source_type = 'CLAIMED_WORKITEM'"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
        parent_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_agent_execution "
                    "WHERE tenant_id = :tenant_id "
                    "AND agent_execution_id = :execution_id"
                ),
                {"tenant_id": tenant_id, "execution_id": parent_execution_id},
            ).scalar_one()
        )
    failure_code = (
        None if result.step_result is None else result.step_result.get("error_ref")
    )
    return {
        "checks": {
            "delegate_authorization_denied_at_create": result.disposition == "TERMINAL"
            and failure_code == "wc.work_item_authorization_denied",
            "wc_database_identity": wc_identity == ("nex_wc_test", "nex_wc_user"),
            "parent_execution_preserved": parent_count == 1,
            "no_wc_work_item_mutation": wc_counts["wc_work_item"] == 0,
            "no_wc_claim_or_assignment": wc_counts["wc_claim"] == 0
            and wc_counts["wc_assignment"] == 0,
            "no_claim_handoff": handoff_count == 0,
            "no_child_agent_execution": child_execution_count == 0,
            "no_child_runtime_job": child_runtime_job_count == 0,
        },
        "row_counts": {
            **wc_counts,
            "claim_execution_handoff": handoff_count,
            "child_agent_execution": child_execution_count,
            "child_runtime_job": child_runtime_job_count,
        },
        "cleanup_counts": cleanup_counts,
    }


def _cleanup_delegate_runtime_rows(factory, *, tenant_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    tables = (
        "ae_external_event_inbox",
        "ae_claim_handoff_inbox",
        "ae_semantic_candidate",
        "ae_step_result",
        "ae_wait_registration",
        "ae_runtime_job_attempt",
        "ae_runtime_job",
    )
    with factory.begin() as session:
        for table in tables:
            counts[table] = int(
                session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
    with factory() as session:
        counts["delegate_runtime_remaining"] = sum(
            int(
                session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in tables
        )
    return counts


def _wc_target_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == "nex_wc_user"
        and unquote(parsed.path.lstrip("/")) == "nex_wc_test"
    )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P7-S5",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    rows = evidence.get("row_counts") or {}
    return (
        "p7_s5_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"waits={rows.get('wait_registration', 0)} "
        f"work_items={rows.get('wc_work_item', 0)} "
        f"cleanup={(evidence.get('cleanup_counts') or {}).get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p7_s5_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
