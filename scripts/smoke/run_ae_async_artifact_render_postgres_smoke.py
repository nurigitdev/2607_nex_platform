#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
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
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_ae_api.artifacts import (  # noqa: E402
    ArtifactHandoffError,
    LocalRenderedArtifactStorage,
    SqlAlchemyArtifactHandoffStore,
    SqlAlchemyArtifactRecordStore,
    register_artifact_handoff_routes,
)
from nex_ae_api.async_artifact_render_recovery import (  # noqa: E402
    inspect_async_artifact_render_recovery,
    reconcile_async_artifact_render,
)
from nex_ae_api.async_artifact_render_worker import (  # noqa: E402
    run_async_artifact_render_worker_once,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    issue_mock_user_token,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402

SCHEMA_VERSION = "ae_async_artifact_render_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ASYNC_ARTIFACT_RENDER_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
DATABASE_NAME = "nex_ae_test"
DATABASE_ROLE = "nex_ae_user"
SERVICE_ID = "nex-ae-api"

SmokeExecutor = Callable[..., dict[str, Any]]


def run_ae_async_artifact_render_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    executor: SmokeExecutor | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1080",
            "requirement": "S108",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }

    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not _target_url_allowed(database_url):
        return _failure(
            "database_target_not_allowed",
            f"Database target must be {DATABASE_ROLE}@.../{DATABASE_NAME}.",
        )

    try:
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile="test",
        )
        evidence = (executor or _execute_postgres_smoke)(database_url=database_url)
        evidence["checks"] = {
            "migration_current": _migration_current(migration),
            **evidence.get("checks", {}),
        }
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "1080",
                "requirement": "S108",
                "actual_postgres": True,
                "database": redact_database_url(database_url),
                "migration": _migration_summary(migration),
                "provider_mode": "deterministic-local-transform",
                "remote_provider_required": False,
                "private_storage_mode": "temporary-local-filesystem",
            }
        )
        evidence["failed_checks"] = [
            name for name, passed in evidence["checks"].items() if not passed
        ]
        evidence["status"] = "PASS" if not evidence["failed_checks"] else "FAIL"
        if evidence["failed_checks"]:
            evidence["failure_code"] = "ae_async_artifact_render_smoke_failed"
        return evidence
    except (MigrationError, SQLAlchemyError, OSError, ValueError, RuntimeError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _execute_postgres_smoke(  # pragma: no cover - protected PostgreSQL evidence
    *,
    database_url: str,
) -> dict[str, Any]:
    probe = uuid4().hex
    trace_id = uuid4().hex
    request_id = f"s108-{probe}"
    tenant_id = f"tenant-s108-{probe[:12]}"
    owner_id = f"owner-s108-{probe[:12]}"
    other_owner_id = f"other-s108-{probe[:12]}"
    workspace_id = f"workspace-s108-{probe[:12]}"
    generation_id = f"generation-s108-{probe[:12]}"
    draft_id = f"draft-s108-{probe[:12]}"
    private_text = f"S108 private rendered evidence {probe} [1]."
    checks: dict[str, bool] = {}
    row_counts: dict[str, int] = {}
    cleanup_counts: dict[str, int] = {}
    artifact_id: str | None = None
    handoff_id: str | None = None
    success_job_id: str | None = None
    retry_job_id: str | None = None

    generation = {
        "cx_generation_id": generation_id,
        "status": "COMPLETED",
        "trace_id": trace_id,
        "request_id": request_id,
        "request_metadata": {
            "structured_draft_id": draft_id,
            "grounding_required": True,
            "retrieval_package_id": f"retrieval-s108-{probe[:12]}",
            "retrieval_package_hash": "d" * 64,
            "selected_evidence_count": 1,
        },
    }
    draft = {
        "structured_draft_schema_version": "cx_structured_draft.v1",
        "structured_draft_id": draft_id,
        "cx_generation_id": generation_id,
        "status": "VALIDATED",
        "trace_id": trace_id,
        "request_id": request_id,
        "title": f"S108 Artifact {probe[:8]}",
        "summary": "Protected asynchronous artifact smoke.",
        "content_hash": "c" * 64,
        "sections": [
            {
                "section_id": f"section-s108-{probe[:12]}",
                "ordinal": 1,
                "heading": "Evidence",
                "blocks": [
                    {
                        "block_id": f"block-s108-{probe[:12]}",
                        "block_type": "paragraph",
                        "text_hash": "e" * 64,
                        "text_preview": private_text,
                    }
                ],
            }
        ],
        "citations": [
            {
                "citation_label": "[1]",
                "evidence_id": f"evidence-s108-{probe[:12]}",
                "retrieval_package_id": f"retrieval-s108-{probe[:12]}",
                "valid": True,
                "validation_error": None,
            }
        ],
        "validation": {
            "validator_profile_id": "s108-smoke-validator-v1",
            "citation_status": "VALIDATED",
            "errors": [],
            "warnings": [],
        },
    }

    class DeterministicCxClient:
        def get_generation(self, cx_generation_id: str, **_: Any) -> dict[str, Any]:
            if cx_generation_id != generation_id:
                raise RuntimeError("unexpected generation")
            return dict(generation)

        def get_structured_draft(
            self, cx_generation_id: str, **_: Any
        ) -> dict[str, Any]:
            if cx_generation_id != generation_id:
                raise RuntimeError("unexpected generation")
            return dict(draft)

    class RetryableFailureCxClient:
        def get_structured_draft(self, *_: Any, **__: Any) -> dict[str, Any]:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="cx.structured_draft_unavailable",
                detail="Deterministic retry probe.",
                retryable=True,
            )

    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    storage_temp = tempfile.TemporaryDirectory(prefix="nex-ae-s108-")
    storage_root = Path(storage_temp.name) / "private-artifacts"
    storage = LocalRenderedArtifactStorage(storage_root)
    handoff_store = SqlAlchemyArtifactHandoffStore(session_factory)
    artifact_store = SqlAlchemyArtifactRecordStore(
        session_factory,
        rendered_storage=storage,
    )
    job_queue = SqlAlchemyJobQueue(session_factory)

    def service_headers() -> dict[str, str]:
        token = issue_mock_service_token(service_id="nex-oa", audience=SERVICE_ID)
        return {
            "Authorization": f"Bearer {token.access_token}",
            "X-Request-ID": request_id,
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        }

    def user_headers(user_id: str) -> dict[str, str]:
        token = issue_mock_user_token(tenant_id=tenant_id, user_id=user_id)
        return {
            "Authorization": f"Bearer {token.access_token}",
            "X-Request-ID": request_id,
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        }

    try:
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_artifact_handoff_routes(
            app,
            store=handoff_store,
            artifact_store=artifact_store,
            job_queue=job_queue,
            cx_client=DeterministicCxClient(),
        )
        with TestClient(app) as client:
            handoff_response = client.post(
                "/api/v1/artifact-handoffs",
                json={
                    "cx_generation_id": generation_id,
                    "chat_document_id": f"chat-document-s108-{probe[:12]}",
                    "interaction_id": f"interaction-s108-{probe[:12]}",
                    "workspace_id": workspace_id,
                    "tenant_id": tenant_id,
                    "owner_user_id": owner_id,
                    "artifact_intent": "create_and_export",
                    "target_formats": ["MD", "HTML_PREVIEW"],
                    "artifact_title": f"S108 Artifact {probe[:8]}",
                    "language": "ko",
                    "actor_claims_ref": {
                        "actor_type": "user",
                        "actor_id": owner_id,
                        "tenant_id": tenant_id,
                    },
                },
                headers={
                    **service_headers(),
                    "Idempotency-Key": f"handoff-s108-{probe}",
                },
            )
            handoff_body = handoff_response.json()
            handoff_id = handoff_body.get("artifact_handoff_id")
            artifact_response = client.post(
                "/api/v1/artifacts",
                json={"artifact_handoff_id": handoff_id},
                headers={
                    **service_headers(),
                    "Idempotency-Key": f"artifact-s108-{probe}",
                },
            )
            artifact_body = artifact_response.json()
            artifact_id = artifact_body.get("artifact_id")
            admitted = client.post(
                f"/api/v1/artifacts/{artifact_id}/async-render-jobs",
                json={"target_formats": ["MD", "HTML_PREVIEW"], "max_attempts": 3},
                headers={
                    **user_headers(owner_id),
                    "Idempotency-Key": f"render-success-s108-{probe}",
                },
            )
            admitted_body = admitted.json()
            success_job_id = admitted_body.get("render", {}).get("render_job_id")
            joined = client.post(
                f"/api/v1/artifacts/{artifact_id}/async-render-jobs",
                json={"target_formats": ["MD", "HTML_PREVIEW"], "max_attempts": 3},
                headers={
                    **user_headers(owner_id),
                    "Idempotency-Key": f"render-success-s108-{probe}",
                },
            )
            hidden = client.get(
                f"/api/v1/async-artifact-render-jobs/{success_job_id}",
                headers=user_headers(other_owner_id),
            )

            restart_engine = build_engine(database_url)
            try:
                restart_factory = build_session_factory(restart_engine)
                restarted_store = SqlAlchemyArtifactRecordStore(
                    restart_factory,
                    rendered_storage=LocalRenderedArtifactStorage(storage_root),
                )
                restarted_queue = SqlAlchemyJobQueue(restart_factory)
                queued_after_restart = restarted_queue.get_job(str(success_job_id))
                render_after_restart = restarted_store.get_render_job(
                    str(success_job_id)
                )
                execution = run_async_artifact_render_worker_once(
                    job_queue=restarted_queue,
                    artifact_store=restarted_store,
                    cx_client=DeterministicCxClient(),
                    worker_id=f"s108-worker-{probe[:12]}",
                )
                completed_artifact = restarted_store.get(str(artifact_id))
                completed_job = restarted_queue.get_job(str(success_job_id))
                rendered_payloads = [
                    restarted_store.get_rendered_artifact_file(item)
                    for item in completed_artifact.get("files", [])
                ]
            finally:
                restart_engine.dispose()

            owner_status = client.get(
                f"/api/v1/async-artifact-render-jobs/{success_job_id}",
                headers=user_headers(owner_id),
            )
            retry_admission = client.post(
                f"/api/v1/artifacts/{artifact_id}/async-render-jobs",
                json={"target_formats": ["MD"], "max_attempts": 3},
                headers={
                    **user_headers(owner_id),
                    "Idempotency-Key": f"render-retry-s108-{probe}",
                },
            )
            retry_job_id = retry_admission.json().get("render", {}).get("render_job_id")
            retry_execution = run_async_artifact_render_worker_once(
                job_queue=job_queue,
                artifact_store=artifact_store,
                cx_client=RetryableFailureCxClient(),
                worker_id=f"s108-retry-worker-{probe[:12]}",
            )
            retry_plan = inspect_async_artifact_render_recovery(
                render_job_id=str(retry_job_id),
                artifact_store=artifact_store,
                job_queue=job_queue,
            )
            retry_render = artifact_store.get_render_job(str(retry_job_id))
            artifact_store.save_render_job_state(
                {
                    **retry_render,
                    "job_status": "RUNNING",
                    "current_stage": "HANDOFF_VALIDATING",
                    "progress_percent": 10,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            reconciliation = reconcile_async_artifact_render(
                render_job_id=str(retry_job_id),
                artifact_store=artifact_store,
                job_queue=job_queue,
                observed_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
            )

        with engine.connect() as connection:
            database_name, database_role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            row_counts = {
                "artifacts": int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_artifacts WHERE artifact_id = :id"
                        ),
                        {"id": artifact_id},
                    ).scalar_one()
                ),
                "render_jobs": int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_artifact_render_jobs "
                            "WHERE artifact_id = :id"
                        ),
                        {"id": artifact_id},
                    ).scalar_one()
                ),
                "queue_jobs": int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM service_jobs WHERE trace_id = :trace_id"
                        ),
                        {"trace_id": trace_id},
                    ).scalar_one()
                ),
                "files": int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_artifact_files WHERE artifact_id = :id"
                        ),
                        {"id": artifact_id},
                    ).scalar_one()
                ),
            }
            metadata_rows = []
            for table_name, predicate, params in (
                ("ae_artifacts", "artifact_id = :id", {"id": artifact_id}),
                (
                    "ae_artifact_source_refs",
                    "artifact_id = :id",
                    {"id": artifact_id},
                ),
                (
                    "ae_artifact_versions",
                    "artifact_id = :id",
                    {"id": artifact_id},
                ),
                (
                    "ae_artifact_render_jobs",
                    "artifact_id = :id",
                    {"id": artifact_id},
                ),
                ("ae_artifact_files", "artifact_id = :id", {"id": artifact_id}),
                ("service_jobs", "trace_id = :trace_id", {"trace_id": trace_id}),
            ):
                metadata_rows.extend(
                    connection.execute(
                        text(
                            f"SELECT row_to_json(probe_row)::text FROM "
                            f"(SELECT * FROM {table_name} WHERE {predicate}) probe_row"
                        ),
                        params,
                    ).scalars()
                )
        metadata_text = " ".join(metadata_rows)
        storage_files = [path for path in storage_root.rglob("*") if path.is_file()]
        checks.update(
            {
                "actual_test_database": database_name == DATABASE_NAME,
                "actual_test_role": database_role == DATABASE_ROLE,
                "handoff_and_artifact_persisted": handoff_response.status_code == 200
                and artifact_response.status_code == 200
                and row_counts["artifacts"] == 1,
                "durable_queue_admission": admitted.status_code == 202
                and admitted_body.get("admission_status") == "ENQUEUED"
                and joined.status_code == 202
                and joined.json().get("admission_status") == "JOINED"
                and row_counts["queue_jobs"] == 2,
                "restart_reads_queued_state": queued_after_restart is not None
                and queued_after_restart.get("status") == "QUEUED"
                and render_after_restart is not None
                and render_after_restart.get("job_status") == "QUEUED",
                "worker_completed_after_restart": execution.status == "SUCCEEDED"
                and completed_job is not None
                and completed_job.get("status") == "SUCCEEDED"
                and completed_artifact is not None
                and completed_artifact.get("artifact_status") == "READY",
                "private_payloads_materialized": len(storage_files) == 2
                and len(rendered_payloads) == 2
                and all(rendered_payloads)
                and private_text.encode("utf-8") in rendered_payloads[0],
                "metadata_only_in_postgres": private_text not in metadata_text
                and str(storage_root) not in metadata_text,
                "owner_isolation_enforced": hidden.status_code == 404
                and owner_status.status_code == 200
                and owner_status.json().get("lifecycle_status") == "READY",
                "bounded_retry_persisted": retry_execution.status == "FAILED"
                and retry_plan.get("action") == "WAIT_FOR_RETRY"
                and retry_plan.get("attempt_count") == 1
                and retry_plan.get("attempts_remaining") == 2,
                "retry_state_reconciled": reconciliation.get("result") == "RECONCILED"
                and reconciliation.get("applied_action") == "RESET_RENDER_TO_QUEUED"
                and reconciliation.get("after", {}).get("action") == "WAIT_FOR_RETRY",
                "expected_row_counts": row_counts
                == {
                    "artifacts": 1,
                    "render_jobs": 2,
                    "queue_jobs": 2,
                    "files": 2,
                },
            }
        )
    finally:
        with engine.begin() as connection:
            cleanup_counts["queue_jobs"] = int(
                connection.execute(
                    text("DELETE FROM service_jobs WHERE trace_id = :trace_id"),
                    {"trace_id": trace_id},
                ).rowcount
                or 0
            )
            if artifact_id:
                cleanup_counts["artifacts"] = int(
                    connection.execute(
                        text("DELETE FROM ae_artifacts WHERE artifact_id = :id"),
                        {"id": artifact_id},
                    ).rowcount
                    or 0
                )
            if handoff_id:
                cleanup_counts["handoffs"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM ae_artifact_handoffs "
                            "WHERE artifact_handoff_id = :id"
                        ),
                        {"id": handoff_id},
                    ).rowcount
                    or 0
                )
            cleanup_counts["remaining"] = int(
                connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM service_jobs WHERE trace_id = :trace_id) + "
                        "(SELECT count(*) FROM ae_artifacts WHERE artifact_id = :artifact_id) + "
                        "(SELECT count(*) FROM ae_artifact_handoffs "
                        " WHERE artifact_handoff_id = :handoff_id)"
                    ),
                    {
                        "trace_id": trace_id,
                        "artifact_id": artifact_id or "",
                        "handoff_id": handoff_id or "",
                    },
                ).scalar_one()
            )
        engine.dispose()
        storage_temp.cleanup()

    checks["database_cleanup_complete"] = cleanup_counts.get("remaining") == 0
    checks["private_storage_cleanup_complete"] = not storage_root.exists()
    return {
        "execution_state": "EXECUTED",
        "database_identity": {
            "database": DATABASE_NAME,
            "role": DATABASE_ROLE,
        },
        "row_counts": row_counts,
        "cleanup_counts": cleanup_counts,
        "rendered_file_count": row_counts.get("files", 0),
        "retry_attempt_count": retry_plan.get("attempt_count"),
        "checks": checks,
    }


def _target_url_allowed(database_url: str) -> bool:
    try:
        parsed = urlsplit(database_url)
        return (
            unquote(parsed.username or "") == DATABASE_ROLE
            and unquote(parsed.path.lstrip("/")) == DATABASE_NAME
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


def _redact_detail(detail: str, *, database_url: str) -> str:
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    if password:
        redacted = redacted.replace(unquote(password), "***")
    return redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1080",
        "requirement": "S108",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"ae_async_artifact_render_postgres=skipped reason={SMOKE_ENV}"
    if evidence.get("status") != "PASS":
        return (
            "ae_async_artifact_render_postgres=fail "
            f"code={evidence.get('failure_code', 'checks_failed')}"
        )
    checks = evidence.get("checks", {})
    cleanup = evidence.get("cleanup_counts", {})
    return (
        "ae_async_artifact_render_postgres=pass "
        f"checks={sum(value is True for value in checks.values())} "
        f"rows={sum(evidence.get('row_counts', {}).values())} "
        f"remaining={cleanup.get('remaining', '?')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ae_async_artifact_render_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
