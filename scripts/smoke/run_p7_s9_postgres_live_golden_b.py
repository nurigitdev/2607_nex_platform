#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-mo",
    ROOT / "services" / "nex-oa",
    ROOT / "services" / "nex-wc",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s5_postgres_smoke as p5_s5  # noqa: E402
import run_p6_ca02_s3_in_process_smoke as p6_ca02_s3  # noqa: E402
import run_p7_s7_postgres_live_e2e as p7_s7  # noqa: E402
import run_p65_s7_postgres_live_e2e as p65_s7  # noqa: E402
from nex_ae_api.delegated_work import (  # noqa: E402
    SqlAlchemyDelegationRuntimeRepository,
    SqlAlchemyWaitRegistrationRepository,
)
from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine  # noqa: E402
from nex_ae_api.plan_finalization import (  # noqa: E402
    SqlAlchemyP5PlanFinalizationService,
)
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue  # noqa: E402
from nex_ae_api.step_executors import (  # noqa: E402
    DelegateWorkExecutorDependencies,
    P5DeterministicProjectionExecutor,
    P5StepExecutionWorker,
    P5StepExecutorRegistry,
    P7DelegateWorkExecutor,
)
from nex_ae_api.work_result_resume import (  # noqa: E402
    SqlAlchemyWorkResultResumeSource,
)
from nex_oa.authorization_repository import (  # noqa: E402
    build_authorization_repository_for_runtime,
)
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver  # noqa: E402
from nex_oa.authorization_service import (  # noqa: E402
    OA_AUTHORIZATION_READ_SCOPE,
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.identity_access import OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE  # noqa: E402
from nex_oa.memberships import (  # noqa: E402
    build_tenant_membership_registry_for_runtime,
    register_identity_membership_routes,
)
from nex_oa.subjects import build_subject_registry_for_runtime  # noqa: E402
from nex_runtime import (  # noqa: E402
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref  # noqa: E402
from nex_wc.work_items import (  # noqa: E402
    SqlAlchemyWorkItemRepository,
    WorkItemService,
)
from run_migrations import run_service_migrations  # noqa: E402
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)

SCHEMA_VERSION = "p7_s9_postgres_live_golden_b.v1"
SMOKE_ENV = "NEX_P7_S9_POSTGRES_LIVE_GOLDEN_B"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
WC_DATABASE_ENV = "NEX_WC_TEST_DATABASE_URL"
OA_DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
NSL_SOURCE_ENV = "NEX_AE_P65_S7_NSL_SOURCE"


class _OaApiAuthorizationSource:
    def __init__(
        self,
        client: TestClient,
        *,
        scopes: tuple[str, ...] = (
            "work:delegate",
            "work:claim",
            "work:result:submit",
        ),
    ) -> None:
        self._client = client
        self._scopes = scopes
        self._seeded: set[tuple[str, str]] = set()
        self.authorization_calls = 0
        self.bootstrap_calls = 0
        self.observed_gates: list[str] = []

    @property
    def tenant_ids(self) -> tuple[str, ...]:
        return tuple(sorted({tenant_id for tenant_id, _ in self._seeded}))

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        key = (tenant_id, subject_id)
        if key not in self._seeded:
            response = self._client.post(
                "/internal/v1/identity/memberships/ensure",
                headers=_service_headers(OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE),
                json={
                    "tenant_id": tenant_id,
                    "subject_id": subject_id,
                    "tenant_display_name": "P7 Golden B Tenant",
                    "subject_display_name": "P7 Golden B Employee",
                    "roles": ["employee"],
                    "scopes": list(self._scopes),
                },
            )
            response.raise_for_status()
            self._seeded.add(key)
            self.bootstrap_calls += 1
        response = self._client.get(
            "/internal/v1/auth/tenants/"
            f"{quote(tenant_id, safe='')}/subjects/{quote(subject_id, safe='')}"
            "/authorization",
            headers=_service_headers(OA_AUTHORIZATION_READ_SCOPE),
        )
        response.raise_for_status()
        authorization = response.json().get("authorization")
        if not isinstance(authorization, dict):
            raise RuntimeError("OA authorization response is invalid")
        gates = ("work:delegate", "work:claim", "work:result:submit")
        self.observed_gates.append(
            gates[self.authorization_calls]
            if self.authorization_calls < len(gates)
            else "unexpected"
        )
        self.authorization_calls += 1
        return {**authorization, "active": True}


def run_p7_s9_postgres_live_golden_b(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P7-S9",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
            "actual_remote_provider": False,
        }
    urls = {
        "ae": env.get(AE_DATABASE_ENV, ""),
        "wc": env.get(WC_DATABASE_ENV, ""),
        "oa": env.get(OA_DATABASE_ENV, ""),
    }
    targets = {
        "ae": ("nex_ae_user", "nex_ae_test"),
        "wc": ("nex_wc_user", "nex_wc_test"),
        "oa": ("nex_oa_user", "nex_oa_test"),
    }
    if any(
        not _target_allowed(urls[name], user=user, database=database)
        for name, (user, database) in targets.items()
    ):
        return _failure(
            "target_not_allowed", "AE, WC, and OA test databases are required."
        )
    nsl_source_value = env.get(NSL_SOURCE_ENV, "")
    if not nsl_source_value:
        return _failure("nsl_source_missing", f"{NSL_SOURCE_ENV} is required.")
    runtime_environ = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_BASE_URL": "http://p7-s9-in-process-mo",
        SERVICE_SPECS["nex-oa"].database_env: urls["oa"],
        "NEX_OA_PERSISTENCE_MODE": "postgres",
    }
    missing = p65_s7._missing_provider_configuration(runtime_environ)
    if missing:
        return _failure(
            "provider_configuration_missing",
            "Protected generation provider configuration is incomplete.",
        )
    try:
        nsl_source = Path(nsl_source_value).resolve(strict=True)
        nsl_lock = json.loads(p6_ca02_s3.DEFAULT_LOCK.read_text(encoding="utf-8"))
        p6_ca02_s3._installed_package_evidence(nsl_source, nsl_lock)
        migrations = {
            service: run_service_migrations(
                service, database_url=urls[key], profile="test"
            )
            for service, key in (
                ("nex-ae-api", "ae"),
                ("nex-wc", "wc"),
                ("nex-oa", "oa"),
            )
        }
        execution = _execute_golden_b(
            urls=urls,
            nsl_source=nsl_source,
            runtime_environ=runtime_environ,
        )
        checks = {
            "all_migrations_current": all(
                len(item.planned) == len(item.applied) + len(item.skipped)
                for item in migrations.values()
            ),
            **dict(execution.get("checks") or {}),
        }
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P7-S9",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "profile": "test",
            "source_revision": _source_revision(),
            "actual_postgres": True,
            "actual_remote_provider": True,
            "redacted_database_urls": {
                key: redact_database_url(value) for key, value in urls.items()
            },
            "migration_heads": {
                service: item.planned[-1] for service, item in migrations.items()
            },
            "nsl_revision": nsl_lock["source_revision"],
            "checks": checks,
            **{key: value for key, value in execution.items() if key != "checks"},
        }
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "p7_s9_acceptance_failed"
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected smoke boundary
        detail = str(exc)
        for value in urls.values():
            detail = p5_s5._redact_detail(detail, database_url=value)
        code = str(getattr(exc, "error_code", type(exc).__name__))
        return _failure("execution_failed", f"{code}: {detail}")


def _execute_golden_b(
    *, urls: Mapping[str, str], nsl_source: Path, runtime_environ: dict[str, str]
) -> dict[str, object]:
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    persistence = attach_service_persistence_runtime(
        app, SERVICE_SPECS["nex-oa"], environ=runtime_environ
    )
    if persistence.api_engine is None or persistence.api_session_factory is None:
        raise RuntimeError("OA PostgreSQL runtime is unavailable")
    subjects = build_subject_registry_for_runtime(persistence)
    memberships = build_tenant_membership_registry_for_runtime(
        persistence, subject_registry=subjects
    )
    repository = build_authorization_repository_for_runtime(persistence)
    service = OaAuthorizationService(
        repository, OaEffectiveAuthorizationResolver(repository), memberships
    )
    register_identity_membership_routes(app, registry=memberships)
    register_authorization_routes(app, service=service)
    source: _OaApiAuthorizationSource | None = None
    result: dict[str, object] = {}
    parent_evidence: dict[str, object] = {}
    cleanup: dict[str, int] = {}
    try:
        with TestClient(app) as client:
            source = _OaApiAuthorizationSource(client)
            result = p7_s7._execute_live_e2e(
                ae_url=urls["ae"],
                wc_url=urls["wc"],
                nsl_source=nsl_source,
                runtime_environ=runtime_environ,
                authorization_source=source,
                parent_resume_verifier=lambda fixture: _capture_parent_completion(
                    fixture, evidence=parent_evidence
                ),
            )
            result.update(parent_evidence)
            oa_observation = _oa_observation(persistence.api_engine, source)
            result["checks"] = {
                **dict(result.get("checks") or {}),
                "actual_oa_database_identity": (
                    oa_observation["database"] == "nex_oa_test"
                    and oa_observation["role"] == "nex_oa_user"
                ),
                "oa_authorization_used_for_all_three_gates": (
                    source.bootstrap_calls == 1
                    and source.authorization_calls == 3
                    and source.observed_gates
                    == ["work:delegate", "work:claim", "work:result:submit"]
                    and oa_observation["membership_count"] == 1
                ),
            }
            result["oa_authorization"] = {
                "bootstrap_calls": source.bootstrap_calls,
                "effective_authorization_calls": source.authorization_calls,
                "work_delegate_gate_calls": source.observed_gates.count(
                    "work:delegate"
                ),
                "work_claim_gate_calls": source.observed_gates.count("work:claim"),
                "work_result_submit_gate_calls": source.observed_gates.count(
                    "work:result:submit"
                ),
            }
    finally:
        if source is not None:
            cleanup = _cleanup_oa(persistence.api_engine, source.tenant_ids)
        _dispose_runtime(persistence)
    result["cleanup_counts"] = {
        **dict(result.get("cleanup_counts") or {}),
        **cleanup,
    }
    result.setdefault("checks", {})["oa_zero_residue"] = (
        cleanup.get("oa_remaining", -1) == 0
    )
    return result


def _capture_parent_completion(
    fixture: Mapping[str, object], *, evidence: dict[str, object]
) -> dict[str, object]:
    completed = _complete_parent_report(fixture)
    evidence.update(
        {
            key: value
            for key, value in completed.items()
            if key not in {"checks", "row_counts"}
        }
    )
    return completed


def _complete_parent_report(fixture: Mapping[str, object]) -> dict[str, object]:
    factory = fixture["factory"]
    wc_factory = fixture["wc_factory"]
    tenant_id = str(fixture["tenant_id"])
    parent = dict(fixture["parent_execution"])
    now = str(fixture["now"])
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    queue = SqlAlchemyRuntimeJobQueue(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    work_items = WorkItemService(
        SqlAlchemyWorkItemRepository(wc_factory),
        authorization_source=fixture["authorization_source"],
    )
    delegate = P7DelegateWorkExecutor(
        dependencies=DelegateWorkExecutorDependencies(
            runtime_repository=SqlAlchemyDelegationRuntimeRepository(factory),
            wait_repository=SqlAlchemyWaitRegistrationRepository(factory),
            work_item_client=p7_s7.p7_s5._DirectWorkItemClient(work_items),
        ),
        clock=lambda: now_dt,
    )
    projection = P5DeterministicProjectionExecutor()
    worker = P5StepExecutionWorker(
        engine=engine,
        jobs=queue,
        executors=P5StepExecutorRegistry(
            {
                "WC_DELEGATE_WORK": delegate,
                "DETERMINISTIC_REPORT": projection,
                "DETERMINISTIC_AGGREGATE": projection,
            }
        ),
        continuation_source=SqlAlchemyWorkResultResumeSource(factory),
        clock=lambda: now_dt,
    )
    resume_claim = queue.claim(
        tenant_id=tenant_id,
        worker_id="p7-s9-parent-resume",
        lease_seconds=60,
        now=now,
    )
    if resume_claim is None or resume_claim.job["job_type"] != "RESUME_EXECUTION":
        raise RuntimeError("P7-S9 parent resume job was not claimable")
    resumed = worker.run_claim(tenant_id=tenant_id, claim=resume_claim)
    if resumed.step_result is None or resumed.step_result["status"] != "SUCCEEDED":
        error_ref = (
            None
            if resumed.step_result is None
            else resumed.step_result.get("error_ref")
        )
        raise RuntimeError(
            f"P7-S9 parent resume did not succeed: {error_ref or resumed.disposition}"
        )
    next_job = engine.schedule_next(
        tenant_id=tenant_id,
        execution_id=str(parent["agent_execution_id"]),
        now=now,
    )
    report_claim = queue.claim(
        tenant_id=tenant_id,
        worker_id="p7-s9-parent-report",
        lease_seconds=60,
        now=now,
    )
    if next_job is None or report_claim is None:
        raise RuntimeError("P7-S9 deterministic parent report was not claimable")
    report = worker.run_claim(tenant_id=tenant_id, claim=report_claim)
    exhausted = engine.schedule_next(
        tenant_id=tenant_id,
        execution_id=str(parent["agent_execution_id"]),
        now=now,
    )
    finalizer = SqlAlchemyP5PlanFinalizationService(factory)
    aggregate = finalizer.finalize(
        tenant_id=tenant_id,
        execution_id=str(parent["agent_execution_id"]),
        created_at=now,
    )
    replayed = finalizer.finalize(
        tenant_id=tenant_id,
        execution_id=str(parent["agent_execution_id"]),
        created_at=now,
    )
    with factory() as session:
        parent_step_results = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_step_result WHERE tenant_id = :tenant_id "
                    "AND agent_execution_id = :execution_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": parent["agent_execution_id"],
                },
            ).scalar_one()
        )
        parent_jobs = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_runtime_job WHERE tenant_id = :tenant_id "
                    "AND execution_id = :execution_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": parent["agent_execution_id"],
                },
            ).scalar_one()
        )
        counts = {
            "agent_execution": _tenant_count(session, "ae_agent_execution", tenant_id),
            "runtime_job": _tenant_count(session, "ae_runtime_job", tenant_id),
            "nsl_backend_run": _tenant_count(session, "ae_nsl_backend_run", tenant_id),
            "resume_job": int(
                session.execute(
                    text(
                        "SELECT count(*) FROM ae_runtime_job WHERE tenant_id = :tenant_id "
                        "AND job_type = 'RESUME_EXECUTION'"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            ),
        }
        prompt_versions = list(
            session.execute(
                text(
                    "SELECT b.binding_key, v.version FROM ae_prompt_bindings AS b "
                    "JOIN ae_prompt_template_versions AS v ON "
                    "v.prompt_template_version_id = b.prompt_template_version_id "
                    "WHERE b.binding_key IN ('ae.intent_resolution.default', "
                    "'ae.context_candidate_extraction.default', "
                    "'ae.plan_builder.default') ORDER BY b.binding_key"
                )
            ).mappings()
        )
    with wc_factory() as session:
        claim_generation = int(
            session.execute(
                text(
                    "SELECT max(claim_generation) FROM wc_claim "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
        work_result_count = _tenant_count(session, "wc_work_result", tenant_id)
    event = dict(fixture["result_event"])
    report_payload = dict(report.step_result or {}).get("result_payload") or {}
    checks = {
        "parent_resume_consumed": resumed.step_result is not None
        and resumed.step_result["status"] == "SUCCEEDED",
        "deterministic_parent_report_completed": report.step_result is not None
        and report.step_result["status"] == "SUCCEEDED"
        and report_payload.get("projection_kind") == "REPORT"
        and exhausted is None,
        "parent_agent_result_finalized": aggregate.result["status"] == "SUCCEEDED"
        and aggregate.execution["phase"] == "RESULT_PUBLISH",
        "parent_finalization_restart_idempotent": replayed == aggregate,
        "golden_b_cardinality": parent_step_results == 2
        and parent_jobs == 3
        and counts["agent_execution"] == 2
        and counts["nsl_backend_run"] == 1
        and counts["resume_job"] == 1
        and work_result_count == 1,
        "prompt_versions_recorded": {
            row["binding_key"]: row["version"] for row in prompt_versions
        }
        == {
            "ae.context_candidate_extraction.default": "v2",
            "ae.intent_resolution.default": "v6",
            "ae.plan_builder.default": "v1",
        },
    }
    return {
        "checks": checks,
        "row_counts": {
            "golden_agent_execution": counts["agent_execution"],
            "golden_runtime_job": counts["runtime_job"],
            "golden_nsl_backend_run": counts["nsl_backend_run"],
            "golden_work_result": work_result_count,
            "golden_resume": counts["resume_job"],
            "golden_parent_step_result": parent_step_results,
        },
        "claim_generation": claim_generation,
        "prompt_registry_versions": [dict(row) for row in prompt_versions],
        "hash_safe_lineage": {
            "work_item": semantic_sha256_hash_ref(
                {"work_item_id": fixture["work_item_id"]}
            ),
            "work_result": semantic_sha256_hash_ref({"result_id": event["result_id"]}),
        },
    }


def _oa_observation(engine, source: _OaApiAuthorizationSource) -> dict[str, object]:
    tenant_ids = source.tenant_ids
    with engine.connect() as connection:
        database, role = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        count = sum(
            int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM oa_tenant_memberships "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for tenant_id in tenant_ids
        )
    return {"database": str(database), "role": str(role), "membership_count": count}


def _cleanup_oa(engine, tenant_ids: tuple[str, ...]) -> dict[str, int]:
    tables = (
        "oa_authz_events",
        "oa_group_roles",
        "oa_group_members",
        "oa_roles",
        "oa_groups",
        "oa_user_sessions",
        "oa_tenant_memberships",
        "oa_subjects",
        "oa_tenants",
    )
    deleted = 0
    with engine.begin() as connection:
        for tenant_id in tenant_ids:
            for table in tables:
                deleted += int(
                    connection.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                        {"tenant_id": tenant_id},
                    ).rowcount
                    or 0
                )
    remaining = 0
    with engine.connect() as connection:
        for tenant_id in tenant_ids:
            remaining += sum(
                int(
                    connection.execute(
                        text(
                            f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"
                        ),
                        {"tenant_id": tenant_id},
                    ).scalar_one()
                )
                for table in tables
            )
    return {"oa_deleted": deleted, "oa_remaining": remaining}


def _service_headers(*scopes: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-wc",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": str(uuid4()),
        "traceparent": f"00-{uuid4().hex}-{uuid4().hex[:16]}-01",
    }


def _dispose_runtime(runtime) -> None:
    for engine in (runtime.api_engine, runtime.worker_engine):
        if engine is not None:
            engine.dispose()


def _tenant_count(connection, table: str, tenant_id: str) -> int:
    return int(
        connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()
    )


def _target_allowed(database_url: str, *, user: str, database: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == user
        and unquote(parsed.path.lstrip("/")) == database
    )


def _source_revision() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    revision = completed.stdout.strip()
    return revision if completed.returncode == 0 and revision else "unavailable"


def _failure(code: str, detail: str) -> dict[str, object]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P7-S9",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "actual_remote_provider": False,
    }


def summary_line(evidence: Mapping[str, object]) -> str:
    checks = dict(evidence.get("checks") or {})
    rows = dict(evidence.get("row_counts") or {})
    provider = dict(evidence.get("provider") or {})
    return (
        "p7_s9_postgres_live_golden_b="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"provider_stages={len(provider.get('semantic_stages') or [])} "
        f"executions={rows.get('golden_agent_execution', 0)} "
        f"resume={rows.get('golden_resume', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p7_s9_postgres_live_golden_b()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
