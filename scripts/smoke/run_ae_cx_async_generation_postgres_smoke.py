#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_ae_api.chat import SqlAlchemyChatInteractionStore, register_chat_routes  # noqa: E402
from nex_ae_api.cx_async_generation_client import (  # noqa: E402
    CxAsyncGenerationClientError,
)
from nex_ae_api.cx_owner_context import cx_owner_scope_from_payload  # noqa: E402
from nex_ae_api.prompt_persistence import (  # noqa: E402
    SqlAlchemyAePromptRegistryStore,
)
from nex_ae_api.prompts import seed_ae_prompt_registry  # noqa: E402
from nex_cx.async_generation_operations import (  # noqa: E402
    register_async_generation_operations_routes,
)
from nex_cx.generation_read_model import GenerationReadModel  # noqa: E402
from nex_cx.generation_repository import (  # noqa: E402
    SqlAlchemyGenerationRuntimeRepository,
)
from nex_cx.generation_runtime import (  # noqa: E402
    GroundedGenerationRuntime,
    SqlAlchemyGenerationAdmissionRepository,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402
from nex_cx.worker_leases import SqlAlchemyCxWorkerLeaseStore  # noqa: E402
from nex_runtime import (  # noqa: E402
    OperationalEventEmitter,
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    SqlAlchemyOperationalEventStore,
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_cx_async_generation_postgres_smoke import (  # noqa: E402
    DeterministicMockGenerationClient,
    _cleanup_probe_rows,
    _probe_residue,
    _run_worker,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ae_cx_async_generation_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_CX_ASYNC_POSTGRES_SMOKE"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
CX_DATABASE_ENV = "NEX_CX_TEST_DATABASE_URL"
AE_DATABASE = "nex_ae_test"
CX_DATABASE = "nex_cx_test"
AE_ROLE = "nex_ae_user"
CX_ROLE = "nex_cx_user"
PRIVATE_OUTPUT = "Deterministic asynchronous generation response."

SmokeExecutor = Callable[..., dict[str, Any]]


def run_ae_cx_async_generation_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    executor: SmokeExecutor | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1040",
            "requirement": "S104",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    ae_url = env.get(AE_DATABASE_ENV, "")
    cx_url = env.get(CX_DATABASE_ENV, "")
    if not ae_url or not cx_url:
        return _failure(
            "database_url_missing",
            f"{AE_DATABASE_ENV} and {CX_DATABASE_ENV} are required.",
        )
    if not _target_url_allowed(ae_url, role=AE_ROLE, database=AE_DATABASE):
        return _failure(
            "ae_target_not_allowed",
            f"AE database target must be {AE_ROLE}@.../{AE_DATABASE}.",
        )
    if not _target_url_allowed(cx_url, role=CX_ROLE, database=CX_DATABASE):
        return _failure(
            "cx_target_not_allowed",
            f"CX database target must be {CX_ROLE}@.../{CX_DATABASE}.",
        )

    try:
        ae_migration = run_service_migrations(
            "nex-ae-api", database_url=ae_url, profile="test"
        )
        cx_migration = run_service_migrations(
            "nex-cx", database_url=cx_url, profile="test"
        )
        execute = executor or _execute_postgres_smoke
        evidence = execute(ae_database_url=ae_url, cx_database_url=cx_url)
        evidence["checks"] = {
            "ae_migration_current": _migration_current(ae_migration),
            "cx_migration_current": _migration_current(cx_migration),
            **evidence.get("checks", {}),
        }
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "1040",
                "requirement": "S104",
                "actual_postgres": True,
                "provider_mode": "deterministic-mock",
                "remote_provider_required": False,
                "databases": {
                    "ae": redact_database_url(ae_url),
                    "cx": redact_database_url(cx_url),
                },
                "migrations": {
                    "ae": _migration_summary(ae_migration),
                    "cx": _migration_summary(cx_migration),
                },
            }
        )
        failed_checks = [
            name for name, passed in evidence["checks"].items() if not passed
        ]
        evidence["failed_checks"] = failed_checks
        evidence["status"] = "PASS" if not failed_checks else "FAIL"
        if failed_checks:
            evidence["failure_code"] = "ae_cx_async_postgres_smoke_failed"
        return evidence
    except (MigrationError, SQLAlchemyError, OSError, ValueError, RuntimeError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_urls=(ae_url, cx_url)),
        )
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _execute_postgres_smoke(  # pragma: no cover - protected PostgreSQL evidence
    *,
    ae_database_url: str,
    cx_database_url: str,
) -> dict[str, Any]:
    probe = uuid4().hex
    trace_id = uuid4().hex
    request_id = f"s104-{probe}"
    interaction_id = str(uuid4())
    tenant_id = f"tenant-s104-{probe[:12]}"
    owner_id = f"owner-s104-{probe[:12]}"
    other_owner_id = f"other-s104-{probe[:12]}"
    private_message = f"S104 private async question {probe}."
    checks: dict[str, bool] = {}
    row_counts: dict[str, int] = {}
    cleanup_counts: dict[str, int] = {}
    render_event_id: str | None = None
    job_id: str | None = None

    ae_engine = build_engine(ae_database_url)
    ae_factory = build_session_factory(ae_engine)
    ae_prompt_store = SqlAlchemyAePromptRegistryStore(ae_factory)
    ae_chat_store = SqlAlchemyChatInteractionStore(ae_factory)
    ae_event_store = SqlAlchemyOperationalEventStore(ae_factory)
    seed_ae_prompt_registry(ae_prompt_store)

    cx_app = build_service_app(SERVICE_SPECS["nex-cx"])
    cx_runtime = attach_service_persistence_runtime(
        cx_app,
        SERVICE_SPECS["nex-cx"],
        environ={
            SERVICE_SPECS["nex-cx"].database_env: cx_database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
        },
    )
    if (
        cx_runtime.api_engine is None
        or cx_runtime.worker_engine is None
        or cx_runtime.api_session_factory is None
        or cx_runtime.worker_session_factory is None
    ):
        raise RuntimeError("CX PostgreSQL persistence runtime is unavailable")

    with tempfile.TemporaryDirectory(prefix="nex-cx-s104-") as temp_dir:
        request_store = FileSystemCxPrivateTextStore(Path(temp_dir) / "requests")
        output_store = FileSystemCxPrivateTextStore(Path(temp_dir) / "outputs")
        generation_repository = SqlAlchemyGenerationRuntimeRepository(
            cx_runtime.api_session_factory,
            source_kind="s104-postgres",
        )
        generation_runtime = GroundedGenerationRuntime(
            admission_repository=SqlAlchemyGenerationAdmissionRepository(
                cx_runtime.api_session_factory
            ),
            execution_repository=generation_repository,
            private_output_store=output_store,
        )
        read_model = GenerationReadModel(generation_repository, output_store)
        register_async_generation_operations_routes(
            cx_app,
            job_queue=cx_runtime.job_queue,
            runtime=generation_runtime,
            request_store=request_store,
            read_model=read_model,
            event_emitter=OperationalEventEmitter(
                service_id="nex-cx",
                store=cx_runtime.operational_event_store,
            ),
        )
        leases = SqlAlchemyCxWorkerLeaseStore(
            cx_runtime.worker_session_factory
        )

        try:
            with TestClient(cx_app) as cx_client:
                async_client = _test_client_adapter(cx_client)
                ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
                register_chat_routes(
                    ae_app,
                    store=ae_chat_store,
                    cx_client=_unexpected_sync_client(),
                    cx_async_client=async_client,
                    retrieval_client=_unexpected_retrieval_client(),
                    prompt_store=ae_prompt_store,
                    event_emitter=OperationalEventEmitter(
                        service_id="nex-ae-api",
                        store=ae_event_store,
                    ),
                )
                with TestClient(ae_app) as ae_client:
                    headers = _ae_headers(
                        tenant_id,
                        owner_id,
                        trace_id=trace_id,
                        request_id=request_id,
                    )
                    admission = ae_client.post(
                        "/api/v1/chat/interactions",
                        json={
                            "interaction_id": interaction_id,
                            "user_message": private_message,
                            "generation": {
                                "execution_strategy": "ASYNCHRONOUS"
                            },
                        },
                        headers=headers,
                    )
                    admission_body = admission.json()
                    projection = (
                        admission_body.get("generation", {}).get(
                            "async_generation", {}
                        )
                    )
                    job_id = projection.get("job_id")
                    provider = DeterministicMockGenerationClient()
                    worker_result = _run_worker(
                        cx_runtime.job_queue,
                        leases,
                        generation_runtime,
                        request_store,
                        provider,
                        worker_id=f"s104-worker-{probe}",
                        observed_at=datetime.now(UTC) + timedelta(seconds=5),
                    )
                    refresh = ae_client.post(
                        f"/api/v1/chat/interactions/{interaction_id}/refresh",
                        headers=headers,
                    )
                    refresh_body = refresh.json()
                    other_ae = ae_client.get(
                        f"/api/v1/chat/interactions/{interaction_id}",
                        headers=_ae_headers(
                            tenant_id,
                            other_owner_id,
                            trace_id=trace_id,
                            request_id=request_id,
                        ),
                    )
                    other_cx = cx_client.get(
                        f"/api/v1/generation-jobs/{job_id}",
                        headers=_cx_headers(
                            tenant_id,
                            other_owner_id,
                            trace_id=trace_id,
                            request_id=request_id,
                        ),
                    )

            completed = refresh_body.get("interaction", {})
            result = refresh_body.get("result", {})
            render_event_id = (
                completed.get("generation", {})
                .get("policy", {})
                .get("prompt_render_event_ref", {})
                .get("prompt_render_event_id")
            )
            with ae_engine.connect() as connection:
                ae_database, ae_role = connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
                generation_summary = connection.execute(
                    text(
                        "SELECT generation_summary FROM ae_chat_interactions "
                        "WHERE chat_interaction_id = :interaction_id"
                    ),
                    {"interaction_id": interaction_id},
                ).scalar_one()
                row_counts["ae_chat"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_chat_interactions "
                            "WHERE chat_interaction_id = :interaction_id"
                        ),
                        {"interaction_id": interaction_id},
                    ).scalar_one()
                )
                row_counts["ae_events"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM service_operational_events "
                            "WHERE trace_id = :trace_id"
                        ),
                        {"trace_id": trace_id},
                    ).scalar_one()
                )
            with cx_runtime.api_engine.connect() as connection:
                cx_database, cx_role = connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
                row_counts["cx_job"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM service_jobs "
                            "WHERE job_id = :job_id"
                        ),
                        {"job_id": job_id},
                    ).scalar_one()
                )
                row_counts["cx_execution"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM cx_generation_executions "
                            "WHERE trace_id = :trace_id"
                        ),
                        {"trace_id": trace_id},
                    ).scalar_one()
                )

            ae_restart_engine = build_engine(ae_database_url)
            cx_restart_engine = build_engine(cx_database_url)
            try:
                restarted_chat = SqlAlchemyChatInteractionStore(
                    build_session_factory(ae_restart_engine)
                ).get_for_owner(
                    interaction_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_id,
                )
                restarted_job = SqlAlchemyJobQueue(
                    build_session_factory(cx_restart_engine)
                ).get_job(str(job_id))
            finally:
                ae_restart_engine.dispose()
                cx_restart_engine.dispose()

            persisted_summary = json.dumps(
                generation_summary, ensure_ascii=False, sort_keys=True
            )
            checks.update(
                {
                    "actual_ae_test_database": ae_database == AE_DATABASE,
                    "actual_ae_test_role": ae_role == AE_ROLE,
                    "actual_cx_test_database": cx_database == CX_DATABASE,
                    "actual_cx_test_role": cx_role == CX_ROLE,
                    "ae_admission_persisted": admission.status_code == 202
                    and admission_body.get("status") == "PENDING"
                    and row_counts["ae_chat"] == 1,
                    "cx_job_persisted": row_counts["cx_job"] == 1,
                    "cx_worker_completed": worker_result["succeeded_count"] == 1
                    and provider.call_count == 1,
                    "cx_execution_persisted": row_counts["cx_execution"] == 1,
                    "ae_refresh_completed": refresh.status_code == 200
                    and completed.get("status") == "COMPLETED"
                    and result.get("handoff_status") == "READY",
                    "content_transient_and_verified": result.get("content")
                    == PRIVATE_OUTPUT
                    and refresh_body.get("content_persisted_by_ae") is False
                    and PRIVATE_OUTPUT not in persisted_summary,
                    "ae_restart_read": restarted_chat is not None
                    and restarted_chat.get("status") == "COMPLETED",
                    "cx_restart_read": restarted_job is not None
                    and restarted_job.get("status") == "SUCCEEDED",
                    "owner_isolation_enforced": other_ae.status_code == 404
                    and other_cx.status_code == 404,
                    "ae_events_persisted": row_counts["ae_events"] >= 3,
                }
            )
        finally:
            with ae_engine.begin() as connection:
                cleanup_counts["ae_events"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM service_operational_events "
                            "WHERE trace_id = :trace_id OR request_id = :request_id"
                        ),
                        {"trace_id": trace_id, "request_id": request_id},
                    ).rowcount
                    or 0
                )
                cleanup_counts["ae_chat"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM ae_chat_interactions "
                            "WHERE chat_interaction_id = :interaction_id"
                        ),
                        {"interaction_id": interaction_id},
                    ).rowcount
                    or 0
                )
                if render_event_id:
                    cleanup_counts["ae_render_event"] = int(
                        connection.execute(
                            text(
                                "DELETE FROM ae_prompt_render_events "
                                "WHERE prompt_render_event_id = :event_id"
                            ),
                            {"event_id": render_event_id},
                        ).rowcount
                        or 0
                    )
            _cleanup_probe_rows(
                cx_runtime.api_engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            cleanup_counts["cx_remaining"] = _probe_residue(
                cx_runtime.api_engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            with ae_engine.connect() as connection:
                cleanup_counts["ae_remaining"] = sum(
                    int(value)
                    for value in connection.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM ae_chat_interactions "
                            " WHERE chat_interaction_id = :interaction_id), "
                            "(SELECT count(*) FROM service_operational_events "
                            " WHERE trace_id = :trace_id OR request_id = :request_id), "
                            "(SELECT count(*) FROM ae_prompt_render_events "
                            " WHERE prompt_render_event_id = :event_id)"
                        ),
                        {
                            "interaction_id": interaction_id,
                            "trace_id": trace_id,
                            "request_id": request_id,
                            "event_id": render_event_id or "missing",
                        },
                    ).one()
                )
            checks["cleanup_complete"] = (
                cleanup_counts["ae_remaining"] == 0
                and cleanup_counts["cx_remaining"] == 0
            )
            ae_engine.dispose()
            cx_runtime.api_engine.dispose()
            cx_runtime.worker_engine.dispose()

    return {
        "execution_state": "EXECUTED",
        "database_identity": {
            "ae": {"database": ae_database, "role": ae_role},
            "cx": {"database": cx_database, "role": cx_role},
        },
        "checks": checks,
        "row_counts": row_counts,
        "cleanup_counts": cleanup_counts,
        "probe_id": probe,
    }


def _test_client_adapter(cx_client):  # pragma: no cover
    class Adapter:
        def admit_generation(
            self, payload, *, request_id, trace_id, idempotency_key
        ):
            tenant_id, subject_id = cx_owner_scope_from_payload(payload)
            response = cx_client.post(
                "/api/v1/generation-jobs",
                json=payload,
                headers={
                    **_cx_headers(
                        tenant_id,
                        subject_id,
                        trace_id=trace_id,
                        request_id=request_id,
                    ),
                    "Idempotency-Key": idempotency_key,
                },
            )
            return self._body(response)

        def get_handoff(
            self, job_id, *, tenant_id, subject_id, request_id, trace_id
        ):
            response = cx_client.get(
                f"/api/v1/generation-jobs/{job_id}/handoff",
                headers=_cx_headers(
                    tenant_id,
                    subject_id,
                    trace_id=trace_id,
                    request_id=request_id,
                ),
            )
            return self._body(response)

        def get_job(self, job_id, **kwargs):
            response = cx_client.get(
                f"/api/v1/generation-jobs/{job_id}",
                headers=_cx_headers(
                    kwargs["tenant_id"],
                    kwargs["subject_id"],
                    trace_id=kwargs["trace_id"],
                    request_id=kwargs["request_id"],
                ),
            )
            return self._body(response)

        def cancel_job(self, job_id, **kwargs):
            response = cx_client.post(
                f"/api/v1/generation-jobs/{job_id}/cancel",
                headers=_cx_headers(
                    kwargs["tenant_id"],
                    kwargs["subject_id"],
                    trace_id=kwargs["trace_id"],
                    request_id=kwargs["request_id"],
                ),
            )
            return self._body(response)

        @staticmethod
        def _body(response):
            body = response.json()
            if response.status_code >= 400:
                raise CxAsyncGenerationClientError(
                    response.status_code,
                    body.get("error_code", "cx.async_generation.failed"),
                    body.get("detail", "CX async generation request failed."),
                    body.get("retryable") is True,
                )
            return body

    return Adapter()


def _unexpected_sync_client():  # pragma: no cover
    class Client:
        def create_generation(self, *args, **kwargs):
            raise AssertionError("synchronous generation must not be called")

    return Client()


def _unexpected_retrieval_client():  # pragma: no cover
    class Client:
        def create_retrieval_context(self, *args, **kwargs):
            raise AssertionError("retrieval must not be called")

    return Client()


def _ae_headers(
    tenant_id: str,
    owner_id: str,
    *,
    trace_id: str,
    request_id: str,
) -> dict[str, str]:
    token = issue_mock_user_token(tenant_id=tenant_id, user_id=owner_id)
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _cx_headers(
    tenant_id: str,
    owner_id: str,
    *,
    trace_id: str,
    request_id: str,
) -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-NEX-Tenant-ID": tenant_id,
        "X-NEX-Subject-ID": owner_id,
    }


def _target_url_allowed(database_url: str, *, role: str, database: str) -> bool:
    try:
        parsed = urlsplit(database_url)
        return (
            unquote(parsed.username or "") == role
            and unquote(parsed.path.lstrip("/")) == database
        )
    except ValueError:
        return False


def _migration_current(migration: object) -> bool:
    planned = tuple(getattr(migration, "planned", ()))
    applied = tuple(getattr(migration, "applied", ()))
    skipped = tuple(getattr(migration, "skipped", ()))
    return bool(planned) and len(planned) == len(applied) + len(skipped)


def _migration_summary(migration: object) -> dict[str, Any]:
    planned = tuple(getattr(migration, "planned", ()))
    return {
        "planned_count": len(planned),
        "applied_count": len(tuple(getattr(migration, "applied", ()))),
        "skipped_count": len(tuple(getattr(migration, "skipped", ()))),
        "latest_version": planned[-1] if planned else None,
    }


def _redact_detail(detail: str, *, database_urls: tuple[str, ...]) -> str:
    redacted = detail
    for database_url in database_urls:
        redacted = redacted.replace(database_url, redact_database_url(database_url))
        password = urlsplit(database_url).password
        if password:
            redacted = redacted.replace(unquote(password), "***")
    return redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1040",
        "requirement": "S104",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"ae_cx_async_postgres=skipped reason={SMOKE_ENV}"
    checks = evidence.get("checks") or {}
    cleanup = evidence.get("cleanup_counts") or {}
    identity = evidence.get("database_identity") or {}
    return (
        "ae_cx_async_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"ae={identity.get('ae', {}).get('database', 'not-run')} "
        f"cx={identity.get('cx', {}).get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"cleanup={cleanup.get('ae_remaining', 'not-run')}/"
        f"{cleanup.get('cx_remaining', 'not-run')} "
        f"remote_required={evidence.get('remote_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected AE-to-CX async PostgreSQL integration smoke."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_cx_async_generation_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
