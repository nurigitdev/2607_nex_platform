#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Callable, Mapping

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_ae_api.artifacts import (  # noqa: E402
    LocalRenderedArtifactStorage,
    SqlAlchemyArtifactHandoffStore,
    SqlAlchemyArtifactRecordStore,
    register_artifact_handoff_routes,
)
from nex_ae_api.async_artifact_render_worker import (  # noqa: E402
    run_async_artifact_render_worker_once,
)
from nex_ae_api.generated_response_lineage import (  # noqa: E402
    generated_response_lineage_from_record,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    issue_mock_user_token,
)
import run_ae_web_grounded_generation_playwright_postgres_smoke as base  # noqa: E402
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)


SCHEMA_VERSION = "platform_grounded_generation_artifact_live_postgres_smoke.v1"
SMOKE_ENV = "NEX_S137_GROUNDED_ARTIFACT_LIVE_POSTGRES_SMOKE"
PROFILE_ENV = f"{SMOKE_ENV}_PROFILE"
DEFAULT_PROFILE = "test"
PROTECTED_ENV_KEYS = (
    base.AE_DATABASE_ENV,
    base.CX_DATABASE_ENV,
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_API_KEY",
)

SourceRunner = Callable[..., dict[str, Any]]
ResidueReader = Callable[[Mapping[str, str]], dict[str, int]]


class ArtifactJourneySmokeError(RuntimeError):
    def __init__(self, stage: str, error_code: str | None = None) -> None:
        safe_code = _safe_identifier(error_code) if error_code else None
        self.smoke_stage = ".".join(
            part for part in (stage, safe_code) if part
        )
        super().__init__(self.smoke_stage)


@dataclass(frozen=True)
class TestClientCxArtifactSourceClient:
    client: TestClient

    def get_generation(
        self,
        cx_generation_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._get(
            f"/api/v1/generations/{cx_generation_id}",
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_structured_draft(
        self,
        cx_generation_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._get(
            f"/api/v1/generations/{cx_generation_id}/structured-draft",
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            request_id=request_id,
            trace_id=trace_id,
        )

    def _get(  # pragma: no cover - protected in-process service call
        self,
        path: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        token = issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-cx",
            scopes=("service:call",),
        )
        response = self.client.get(
            path,
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "X-Service-ID": "nex-ae-api",
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                "X-NEX-Tenant-ID": tenant_id,
                "X-NEX-Subject-ID": owner_user_id,
            },
        )
        stage = (
            "read_cx_structured_draft"
            if path.endswith("/structured-draft")
            else "read_cx_generation"
        )
        _require_success(response, stage)
        return response.json()


def run_platform_grounded_generation_artifact_live_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    source_runner: SourceRunner | None = None,
    residue_reader: ResidueReader | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1370",
            "requirement": "S137",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
            "live_provider_required": True,
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", f"{PROFILE_ENV} must be test.")

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        base.SMOKE_ENV: "1",
        base.PROFILE_ENV: DEFAULT_PROFILE,
        "NEX_MO_PROVIDER_MODE": "live",
    }
    run_source = source_runner or _run_source_journey
    source = run_source(effective_env)
    if source.get("status") != "PASS":
        result = _failure(
            "source_journey_failed",
            str(source.get("failure_code") or source.get("status") or "FAIL"),
        )
        result["source_status"] = _source_status(source)
        _assert_redacted(result, effective_env)
        return result

    extension = _mapping(source.get("extension_observation"))
    extension_checks = _bool_mapping(extension.get("checks"))
    read_residue = residue_reader or _read_post_journey_residue
    residue = read_residue(effective_env)
    source_checks = _bool_mapping(source.get("checks"))
    checks = {
        "single_correlated_journey": (
            source.get("evidence_mode") == "single_correlated_browser_request"
        ),
        "actual_ae_and_cx_postgres": (
            source.get("actual_postgres") is True
            and source_checks.get("actual_ae_test_database") is True
            and source_checks.get("actual_cx_test_database") is True
        ),
        "live_retrieval_and_generation_completed": all(
            source_checks.get(name) is True
            for name in (
                "cx_retrieval_persisted",
                "cx_generation_persisted",
                "all_live_provider_capabilities_called",
            )
        ),
        "ae_response_lineage_persisted": (
            source_checks.get("ae_chat_persisted") is True
            and extension_checks.get("response_lineage_bound") is True
        ),
        "artifact_admitted_and_rendered": all(
            extension_checks.get(name) is True
            for name in (
                "grounded_artifact_admitted",
                "restart_worker_completed",
                "artifact_ready_with_exact_lineage",
            )
        ),
        "owner_preview_and_download_ready": all(
            extension_checks.get(name) is True
            for name in (
                "owner_preview_ready",
                "owner_download_ready",
                "cross_owner_hidden",
            )
        ),
        "metadata_and_evidence_are_private_payload_free": (
            extension_checks.get("metadata_only_postgres") is True
            and extension.get("private_payload_included") is False
        ),
        "cleanup_residue_free": bool(residue)
        and all(count == 0 for count in residue.values()),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    result = {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1370",
        "requirement": "S137",
        "status": "PASS" if not failed_checks else "FAIL",
        "failure_code": (
            None
            if not failed_checks
            else "grounded_generation_artifact_live_checks_failed"
        ),
        "profile": profile,
        "actual_postgres": True,
        "live_provider_required": True,
        "services": ["nex-ae-web", "nex-ae-api", "nex-cx", "nex-mo"],
        "source_status": _source_status(source),
        "artifact_observation": {
            key: value
            for key, value in extension.items()
            if key != "checks"
        },
        "post_journey_residue": residue,
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "provider_capability_count": 3,
            "database_count": 2,
        },
    }
    _assert_redacted(result, effective_env)
    return result


def _run_source_journey(env: dict[str, str]) -> dict[str, Any]:
    return base.run_ae_web_grounded_generation_playwright_postgres_smoke(
        env,
        executor=lambda **kwargs: base._execute_live_browser_smoke(
            **kwargs,
            journey_hook=_execute_artifact_journey,
        ),
    )


def _execute_artifact_journey(  # pragma: no cover - protected DB/DGX evidence
    context: dict[str, Any],
) -> dict[str, Any]:
    ae_database_url = str(context["ae_database_url"])
    ae_engine = context["ae_engine"]
    ae_factory = context["ae_factory"]
    chat_store = context["ae_chat_store"]
    cx_client = context["cx_client"]
    tenant_id = str(context["tenant_id"])
    owner_id = str(context["owner_id"])
    interaction_id = str(context["interaction_id"])
    trace_id = str(context["trace_id"])
    request_id = str(context["request_id"])
    artifact_storage_root = Path(context["storage_root"]) / "ae-artifacts"
    source_client = TestClientCxArtifactSourceClient(cx_client)
    handoff_store = SqlAlchemyArtifactHandoffStore(ae_factory)
    artifact_store = SqlAlchemyArtifactRecordStore(
        ae_factory,
        rendered_storage=LocalRenderedArtifactStorage(artifact_storage_root),
    )
    queue = SqlAlchemyJobQueue(ae_factory)
    artifact_id: str | None = None
    handoff_id: str | None = None
    render_job_id: str | None = None
    file_id: str | None = None
    checks: dict[str, bool] = {}
    observation: dict[str, Any] = {}
    cleanup = {"queue_jobs": 0, "artifacts": 0, "handoffs": 0, "remaining": 0}
    chat_record = chat_store.get_for_owner(
        interaction_id,
        tenant_id=tenant_id,
        owner_user_id=owner_id,
    )
    if chat_record is None:
        raise RuntimeError("s137_chat_lineage_unavailable")
    lineage = generated_response_lineage_from_record(chat_record)
    if lineage is None:
        raise RuntimeError("s137_generated_response_lineage_unavailable")

    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    app.state.ae_chat_store = chat_store
    register_artifact_handoff_routes(
        app,
        store=handoff_store,
        artifact_store=artifact_store,
        job_queue=queue,
        cx_client=source_client,
    )
    service_token = issue_mock_service_token(
        service_id="nex-oa",
        audience="nex-ae-api",
    )
    user_token = issue_mock_user_token(tenant_id=tenant_id, user_id=owner_id)
    other_token = issue_mock_user_token(
        tenant_id=tenant_id,
        user_id=f"{owner_id}-other",
    )
    common = {
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }
    try:
        with TestClient(app) as client:
            handoff_response = client.post(
                "/api/v1/artifact-handoffs",
                json={
                    "cx_generation_id": context["cx_generation_id"],
                    "chat_document_id": context["chat_document_id"],
                    "interaction_id": interaction_id,
                    "workspace_id": context["workspace_id"],
                    "tenant_id": tenant_id,
                    "owner_user_id": owner_id,
                    "artifact_intent": "create_and_export",
                    "target_formats": ["MD", "HTML_PREVIEW"],
                    "artifact_title": "S137 grounded artifact",
                    "language": "ko",
                    "actor_claims_ref": {
                        "actor_type": "user",
                        "actor_id": owner_id,
                        "tenant_id": tenant_id,
                    },
                },
                headers={
                    **common,
                    "Authorization": f"Bearer {service_token.access_token}",
                    "Idempotency-Key": f"s137-handoff-{interaction_id}",
                },
            )
            _require_success(handoff_response, "create_handoff")
            handoff_id = str(handoff_response.json()["artifact_handoff_id"])
            admitted = client.post(
                f"/api/v1/generated-responses/{lineage['response_id']}/artifacts",
                json={
                    "artifact_handoff_id": handoff_id,
                    "target_formats": ["MD", "HTML_PREVIEW"],
                    "max_attempts": 3,
                },
                headers={
                    **common,
                    "Authorization": f"Bearer {user_token.access_token}",
                    "Idempotency-Key": f"s137-artifact-{interaction_id}",
                },
            )
            _require_success(admitted, "admit_grounded_artifact")
            admission = admitted.json()
            artifact_id = str(admission["artifact"]["artifact_id"])
            render_job_id = str(
                admission["render_admission"]["render"]["render_job_id"]
            )

            restart_engine = build_engine(ae_database_url)
            try:
                restart_factory = build_session_factory(restart_engine)
                restarted_store = SqlAlchemyArtifactRecordStore(
                    restart_factory,
                    rendered_storage=LocalRenderedArtifactStorage(
                        artifact_storage_root
                    ),
                )
                restarted_queue = SqlAlchemyJobQueue(restart_factory)
                worker = run_async_artifact_render_worker_once(
                    job_queue=restarted_queue,
                    artifact_store=restarted_store,
                    cx_client=source_client,
                    worker_id=f"s137-artifact-{interaction_id[:12]}",
                )
                artifact = restarted_store.get(artifact_id)
            finally:
                restart_engine.dispose()

            if artifact is None or not artifact.get("files"):
                raise RuntimeError("s137_rendered_artifact_unavailable")
            md_file = next(
                item for item in artifact["files"] if item["format"] == "MD"
            )
            file_id = str(md_file["artifact_file_id"])
            owner_headers = {
                **common,
                "Authorization": f"Bearer {user_token.access_token}",
            }
            preview = client.get(
                f"/api/v1/artifact-files/{file_id}/preview",
                headers=owner_headers,
            )
            download = client.get(
                f"/api/v1/artifact-files/{file_id}/download",
                headers=owner_headers,
            )
            hidden = client.get(
                f"/api/v1/artifact-files/{file_id}/preview",
                headers={
                    **common,
                    "Authorization": f"Bearer {other_token.access_token}",
                },
            )
            preview_body = preview.json()
            download_body = download.json()

        with ae_engine.connect() as connection:
            row_counts = {
                "handoffs": _count(
                    connection,
                    "ae_artifact_handoffs",
                    "artifact_handoff_id",
                    handoff_id,
                ),
                "artifacts": _count(
                    connection, "ae_artifacts", "artifact_id", artifact_id
                ),
                "render_jobs": _count(
                    connection,
                    "ae_artifact_render_jobs",
                    "artifact_id",
                    artifact_id,
                ),
                "files": _count(
                    connection, "ae_artifact_files", "artifact_id", artifact_id
                ),
            }
            metadata = " ".join(
                connection.execute(
                    text(
                        "SELECT row_to_json(row_data)::text FROM ("
                        "SELECT * FROM ae_artifacts WHERE artifact_id = :id"
                        ") row_data"
                    ),
                    {"id": artifact_id},
                ).scalars()
            )
        source_ref = artifact["source_refs"][0]
        checks.update(
            {
                "response_lineage_bound": (
                    admission["response_binding"]["response_id"]
                    == lineage["response_id"]
                    and admission["response_binding"]["cx_generation_id"]
                    == lineage["cx_generation_id"]
                    and lineage["citation_workflow_status"] == "VALIDATED"
                ),
                "grounded_artifact_admitted": (
                    admitted.status_code == 202
                    and admission["content_included"] is False
                    and admission["render_admission"]["admission_status"]
                    == "ENQUEUED"
                ),
                "restart_worker_completed": worker.status == "SUCCEEDED",
                "artifact_ready_with_exact_lineage": (
                    artifact["artifact_status"] == "READY"
                    and source_ref["cx_generation_id"]
                    == lineage["cx_generation_id"]
                    and source_ref["retrieval_package_id"]
                    == lineage["retrieval_package_id"]
                    and source_ref["retrieval_package_hash"]
                    == lineage["retrieval_package_hash"]
                ),
                "owner_preview_ready": (
                    preview.status_code == 200
                    and bool(preview_body.get("text_preview"))
                    and "storage_ref" not in json.dumps(preview_body)
                ),
                "owner_download_ready": (
                    download.status_code == 200
                    and bool(download_body.get("content"))
                    and download_body.get("content_hash") == md_file["file_hash"]
                    and "storage_ref" not in json.dumps(download_body)
                ),
                "cross_owner_hidden": hidden.status_code == 404,
                "metadata_only_postgres": (
                    base.SOURCE_TEXT not in metadata
                    and str(artifact_storage_root) not in metadata
                ),
                "expected_rows_persisted": row_counts
                == {
                    "handoffs": 1,
                    "artifacts": 1,
                    "render_jobs": 1,
                    "files": 2,
                },
            }
        )
        observation = {
            "lineage_type": lineage["lineage_type"],
            "citation_workflow_status": lineage["citation_workflow_status"],
            "bounded_repair_applied": lineage["bounded_repair_applied"],
            "artifact_status": artifact["artifact_status"],
            "render_job_status": artifact["render_jobs"][0]["job_status"],
            "rendered_file_count": len(artifact["files"]),
            "preview_sha256": hashlib.sha256(
                str(preview_body.get("text_preview") or "").encode("utf-8")
            ).hexdigest(),
            "download_sha256": download_body.get("content_hash"),
            "row_counts": row_counts,
            "private_payload_included": False,
        }
    finally:
        with ae_engine.begin() as connection:
            if render_job_id:
                cleanup["queue_jobs"] = int(
                    connection.execute(
                        text("DELETE FROM service_jobs WHERE job_id = :job_id"),
                        {"job_id": render_job_id},
                    ).rowcount
                    or 0
                )
            if artifact_id:
                cleanup["artifacts"] = artifact_store.delete(artifact_id)
            if handoff_id:
                cleanup["handoffs"] = handoff_store.delete(handoff_id)
            cleanup["remaining"] = int(
                connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM service_jobs WHERE job_id = :job_id) + "
                        "(SELECT count(*) FROM ae_artifacts WHERE artifact_id = :artifact_id) + "
                        "(SELECT count(*) FROM ae_artifact_handoffs "
                        " WHERE artifact_handoff_id = :handoff_id)"
                    ),
                    {
                        "job_id": render_job_id or "",
                        "artifact_id": artifact_id or "",
                        "handoff_id": handoff_id or "",
                    },
                ).scalar_one()
            )
        shutil.rmtree(artifact_storage_root, ignore_errors=True)
    checks["artifact_cleanup_complete"] = (
        cleanup["remaining"] == 0 and not artifact_storage_root.exists()
    )
    return {**observation, "cleanup": cleanup, "checks": checks}


def _count(connection: Any, table: str, column: str, value: str | None) -> int:
    if value is None:
        return 0
    return int(
        connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE {column} = :value"),
            {"value": value},
        ).scalar_one()
    )


def _require_success(response: Any, stage: str) -> None:
    if 200 <= int(response.status_code) < 300:
        return
    try:
        body = response.json()
    except Exception:
        body = {}
    error_code = body.get("error_code") if isinstance(body, Mapping) else None
    raise ArtifactJourneySmokeError(stage, error_code)


def _safe_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized or len(normalized) > 96:
        return None
    if not all(
        character.isalnum() or character in "._-" for character in normalized
    ):
        return None
    return normalized


def _read_post_journey_residue(  # pragma: no cover - protected DB evidence
    env: Mapping[str, str],
) -> dict[str, int]:
    ae_engine = build_engine(str(env[base.AE_DATABASE_ENV]))
    cx_engine = build_engine(str(env[base.CX_DATABASE_ENV]))
    try:
        with ae_engine.connect() as connection:
            ae = {
                "ae_chat": _owner_count(
                    connection, "ae_chat_interactions", "user_id", base.OWNER_ID
                ),
                "ae_workspaces": _owner_count(
                    connection, "ae_workspaces", "owner_user_id", base.OWNER_ID
                ),
                "ae_artifacts": _owner_count(
                    connection, "ae_artifacts", "owner_user_id", base.OWNER_ID
                ),
                "ae_handoffs": _owner_count(
                    connection,
                    "ae_artifact_handoffs",
                    "owner_user_id",
                    base.OWNER_ID,
                ),
            }
        with cx_engine.connect() as connection:
            cx = {
                "cx_generations": _owner_count(
                    connection,
                    "cx_generation_executions",
                    "owner_subject_ref_id",
                    base.OWNER_ID,
                ),
                "cx_retrieval_packages": _owner_count(
                    connection,
                    "cx_retrieval_packages",
                    "owner_subject_ref_id",
                    base.OWNER_ID,
                ),
                "cx_jobs": _owner_count(
                    connection,
                    "service_jobs",
                    "owner_subject_ref_id",
                    base.OWNER_ID,
                ),
            }
        return {**ae, **cx}
    finally:
        ae_engine.dispose()
        cx_engine.dispose()


def _owner_count(
    connection: Any,
    table: str,
    column: str,
    owner_id: str,
) -> int:
    return int(
        connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE {column} = :owner_id"),
            {"owner_id": owner_id},
        ).scalar_one()
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bool_mapping(value: object) -> dict[str, bool]:
    return {
        str(key): item is True
        for key, item in _mapping(value).items()
    }


def _source_status(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": source.get("status"),
        "failure_code": source.get("failure_code"),
        "detail": source.get("detail"),
        "actual_postgres": source.get("actual_postgres") is True,
        "evidence_mode": source.get("evidence_mode"),
        "failed_check_count": len(source.get("failed_checks") or []),
    }


def _assert_redacted(result: Mapping[str, Any], env: Mapping[str, str]) -> None:
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    lowered = serialized.lower()
    for key in PROTECTED_ENV_KEYS:
        secret = str(env.get(key, ""))
        if secret and secret in serialized:
            raise AssertionError(f"protected value leaked: {key}")
    if base.SOURCE_TEXT in serialized or base.LOGIN_PASSWORD in serialized:
        raise AssertionError("private journey payload leaked")
    for marker in (
        "authorization: bearer",
        "begin private key",
        "postgresql+psycopg://",
        "postgresql://",
    ):
        if marker in lowered:
            raise AssertionError("protected evidence contains a secret marker")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1370",
        "requirement": "S137",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "live_provider_required": True,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return f"platform_grounded_artifact_live=skipped reason={SMOKE_ENV}"
    if result.get("status") != "PASS":
        return (
            "platform_grounded_artifact_live=fail "
            f"code={result.get('failure_code', 'checks_failed')}"
        )
    summary = _mapping(result.get("summary"))
    return (
        "platform_grounded_artifact_live=pass "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"providers={summary.get('provider_capability_count', 0)} "
        f"databases={summary.get('database_count', 0)} residue=0"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_grounded_generation_artifact_live_postgres_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
