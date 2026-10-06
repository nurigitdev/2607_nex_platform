#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-oa",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "services" / "nex-ag",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_ae_api.artifact_access_observability import (  # noqa: E402
    observe_artifact_access,
)
from nex_ae_api.trace_projection import (  # noqa: E402
    SqlAlchemyAeTraceProjectionSource,
    register_ae_trace_projection_routes,
)
from nex_ag.cross_service_trace import (  # noqa: E402
    CrossServiceTraceAggregator,
    HttpCrossServiceTraceSourceClient,
    register_cross_service_trace_routes,
)
from nex_cx.trace_projection import (  # noqa: E402
    SqlAlchemyCxTraceProjectionSource,
    register_cx_trace_projection_routes,
)
from nex_mo.trace_projection import (  # noqa: E402
    MoTraceProjectionSource,
    register_mo_trace_projection_routes,
)
from nex_oa.auth_events import SqlAlchemyOaAuthEventRepository  # noqa: E402
from nex_oa.trace_projection import (  # noqa: E402
    RepositoryOaTraceProjectionSource,
    register_oa_trace_projection_routes,
)
from nex_runtime import (  # noqa: E402
    OperationalEventEmitter,
    SERVICE_SPECS,
    SqlAlchemyOperationalEventStore,
    build_service_app,
    issue_mock_service_token,
    sqlalchemy_database_url,
)
from nex_runtime.postgres_targets import (  # noqa: E402
    ResolvedPostgresTestTarget,
    resolve_postgres_test_targets,
)
from platform_test_migrations import (  # noqa: E402
    PlatformMigrationReadinessResult,
    run_platform_test_migration_readiness,
)

SCHEMA_VERSION = "platform_ag_trace_postgres_smoke.v1"
SMOKE_ENV = "NEX_S138_AG_TRACE_POSTGRES_SMOKE"
PROFILE_ENV = f"{SMOKE_ENV}_PROFILE"
SERVICE_IDS = ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo", "nex-ag")

MigrationRunner = Callable[[Mapping[str, str]], PlatformMigrationReadinessResult]
JourneyRunner = Callable[
    [Sequence[ResolvedPostgresTestTarget]],
    dict[str, Any],
]


class TracePostgresSmokeStepError(RuntimeError):
    def __init__(self, step: str, cause: Exception) -> None:
        detail = cause.__class__.__name__
        constraint = getattr(
            getattr(getattr(cause, "orig", None), "diag", None),
            "constraint_name",
            None,
        )
        if isinstance(constraint, str) and re.fullmatch(r"[a-zA-Z0-9_]+", constraint):
            detail = f"{detail}.{constraint}"
        self.failure_code = f"postgres_journey.{step}.{detail}"
        super().__init__(self.failure_code)


def _run_step(step: str, action: Callable[[], Any]) -> Any:
    try:
        return action()
    except Exception as exc:
        raise TracePostgresSmokeStepError(step, exc) from exc


@dataclass(frozen=True)
class _TestClientRequester:
    client: TestClient

    def __call__(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ):  # pragma: no cover - protected in-process service call
        del timeout
        return self.client.get(urlsplit(url).path, headers=dict(headers))


def run_platform_ag_trace_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    migration_runner: MigrationRunner = run_platform_test_migration_readiness,
    journey_runner: JourneyRunner | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1380",
            "requirement": "S138",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgresql": False,
        }
    if env.get(PROFILE_ENV, "test") != "test":
        return _failure("profile_not_allowed")
    try:
        migrations = migration_runner(env)
        targets = resolve_postgres_test_targets(env, service_ids=SERVICE_IDS)
        journey = (journey_runner or _run_postgres_journey)(targets)
    except TracePostgresSmokeStepError as exc:
        return _failure(exc.failure_code)
    except Exception as exc:
        return _failure(f"execution_failed.{exc.__class__.__name__}")

    families = set(journey.get("stage_families") or [])
    database_identities = dict(journey.get("database_identities") or {})
    residue = dict(journey.get("cleanup_residue") or {})
    checks = {
        "five_migration_heads_current": len(migrations.services) == 5
        and all(item.select_one_ready for item in migrations.services),
        "five_test_database_identities_confirmed": set(database_identities)
        == set(SERVICE_IDS)
        and all(bool(value) for value in database_identities.values()),
        "all_source_service_apis_ready": journey.get("source_statuses")
        == {
            "nex-oa": "READY",
            "nex-ae-api": "READY",
            "nex-cx": "READY",
            "nex-mo": "READY",
            "nex-ag": "READY",
        },
        "all_stage_families_projected": families
        == {
            "AUTH",
            "UPLOAD",
            "INGESTION",
            "RETRIEVAL",
            "GENERATION",
            "ARTIFACT",
            "ACCESS",
            "OPERATIONS",
        },
        "ag_route_returned_canonical_projection": journey.get("status_code") == 200
        and journey.get("projection_schema_version") == "ag_cross_service_trace_e2e.v1",
        "ag_audit_survived_store_restart": journey.get("ag_audit_after_restart") == 1,
        "service_api_only_boundary": journey.get("direct_cross_database_reads") == 0,
        "private_payload_absent": journey.get("private_payload_included") is False,
        "cleanup_residue_free": bool(residue)
        and all(value == 0 for value in residue.values()),
    }
    failed = [name for name, value in checks.items() if not value]
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1380",
        "requirement": "S138",
        "profile": "test",
        "status": "PASS" if not failed else "FAIL",
        "failure_code": None if not failed else "postgres_trace_checks_failed",
        "actual_postgresql": True,
        "actual_service_api": True,
        "remote_provider_required": False,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "service_count": len(database_identities),
            "migration_count": sum(
                item.migration_count for item in migrations.services
            ),
            "stage_count": int(journey.get("stage_count") or 0),
            "stage_family_count": len(families),
            "cleanup_residue_count": sum(residue.values()),
        },
        "database_identities": database_identities,
        "source_statuses": journey.get("source_statuses", {}),
        "stage_families": sorted(families),
        "cleanup_residue": residue,
        "next_slice": "1381" if not failed else "blocked",
    }


def _run_postgres_journey(
    targets: Sequence[ResolvedPostgresTestTarget],
) -> dict[str, Any]:  # pragma: no cover - protected PostgreSQL evidence
    target_by_service = {item.target.service_id: item for item in targets}
    engines = {
        service_id: create_engine(
            sqlalchemy_database_url(target_by_service[service_id].database_url)
        )
        for service_id in SERVICE_IDS
    }
    factories = {
        service_id: sessionmaker(bind=engine, expire_on_commit=False)
        for service_id, engine in engines.items()
    }
    trace_id = uuid4().hex
    ids = _fixture_ids(trace_id)
    seeded = False
    try:
        seeded = True
        identities = _run_step(
            "database_identity",
            lambda: _database_identities(engines, target_by_service),
        )
        _run_step(
            "seed_oa",
            lambda: _seed_oa(factories["nex-oa"], trace_id, ids),
        )
        _run_step(
            "seed_ae",
            lambda: _seed_ae(
                engines["nex-ae-api"],
                factories["nex-ae-api"],
                trace_id,
                ids,
            ),
        )
        _run_step(
            "seed_cx",
            lambda: _seed_cx(engines["nex-cx"], trace_id, ids),
        )
        _run_step(
            "seed_mo",
            lambda: _seed_mo(factories["nex-mo"], trace_id, ids),
        )

        source_clients = _build_source_clients(factories)
        aggregator = CrossServiceTraceAggregator(source_clients)
        ag_store = SqlAlchemyOperationalEventStore(factories["nex-ag"])
        ag_app = build_service_app(SERVICE_SPECS["nex-ag"])
        register_cross_service_trace_routes(
            ag_app,
            aggregator=aggregator,
            event_store=ag_store,
        )
        token = issue_mock_service_token(
            service_id="nex-oa",
            audience="nex-ag",
        ).access_token
        response = TestClient(ag_app).get(
            f"/admin/v1/operations/traces/{trace_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": ids["ag_request_id"],
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
            },
        )
        payload = response.json()

        engines["nex-ag"].dispose()
        restarted_ag_engine = create_engine(
            sqlalchemy_database_url(target_by_service["nex-ag"].database_url)
        )
        restarted_ag_store = SqlAlchemyOperationalEventStore(
            sessionmaker(bind=restarted_ag_engine, expire_on_commit=False)
        )
        restarted_events = restarted_ag_store.list_events(trace_id=trace_id)
        restarted_ag_engine.dispose()

        serialized = json.dumps(payload, sort_keys=True)
        observations = {
            "status_code": response.status_code,
            "projection_schema_version": payload.get("projection_schema_version"),
            "source_statuses": {
                item["service_id"]: item["source_status"]
                for item in payload.get("source_statuses", [])
            },
            "stage_count": payload.get("summary", {}).get("stage_count", 0),
            "stage_families": sorted(
                {item["stage_family"] for item in payload.get("timeline", [])}
            ),
            "ag_audit_after_restart": len(restarted_events),
            "database_identities": identities,
            "direct_cross_database_reads": 0,
            "private_payload_included": (
                payload.get("summary", {}).get("private_payload_included") is True
                or any(
                    marker in serialized.lower()
                    for marker in (
                        "private prompt",
                        "generated_text",
                        "provider_url",
                        "database_url",
                        "storage_ref",
                        "bearer ",
                    )
                )
            ),
        }
        cleanup = _cleanup(engines, trace_id, ids)
        seeded = False
        return {**observations, "cleanup_residue": cleanup}
    finally:
        if seeded:
            try:
                _cleanup(engines, trace_id, ids)
            except Exception:
                pass
        for engine in engines.values():
            engine.dispose()


def _build_source_clients(  # pragma: no cover - protected PostgreSQL evidence
    factories: Mapping[str, Any],
) -> dict[str, Any]:
    oa_app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_oa_trace_projection_routes(
        oa_app,
        source=RepositoryOaTraceProjectionSource(
            SqlAlchemyOaAuthEventRepository(factories["nex-oa"]),
            SqlAlchemyOperationalEventStore(factories["nex-oa"]),
        ),
    )
    ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_ae_trace_projection_routes(
        ae_app,
        source=SqlAlchemyAeTraceProjectionSource(factories["nex-ae-api"]),
    )
    cx_app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_cx_trace_projection_routes(
        cx_app,
        source=SqlAlchemyCxTraceProjectionSource(factories["nex-cx"]),
    )
    mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
    register_mo_trace_projection_routes(
        mo_app,
        source=MoTraceProjectionSource(
            SqlAlchemyOperationalEventStore(factories["nex-mo"])
        ),
    )
    apps = {
        "nex-oa": oa_app,
        "nex-ae-api": ae_app,
        "nex-cx": cx_app,
        "nex-mo": mo_app,
    }
    return {
        service_id: HttpCrossServiceTraceSourceClient(
            service_id=service_id,
            base_url=f"http://{service_id}.test",
            requester=_TestClientRequester(TestClient(app)),
        )
        for service_id, app in apps.items()
    }


def _fixture_ids(trace_id: str) -> dict[str, str]:  # pragma: no cover
    prefix = f"s138-{trace_id[:12]}"
    return {
        "tenant_id": f"tenant-{prefix}",
        "owner_id": f"owner-{prefix}",
        "oa_request_id": f"request-oa-{prefix}",
        "upload_handoff_id": f"upload-{prefix}",
        "artifact_handoff_id": f"handoff-{prefix}",
        "artifact_id": f"artifact-{prefix}",
        "artifact_file_id": f"file-{prefix}",
        "ae_request_id": f"request-ae-{prefix}",
        "source_file_id": str(uuid4()),
        "content_id": str(uuid4()),
        "upload_id": str(uuid4()),
        "job_id": f"job-{prefix}",
        "ingest_run_id": str(uuid4()),
        "retrieval_id": str(uuid4()),
        "generation_id": f"generation-{prefix}",
        "cx_request_id": f"request-cx-{prefix}",
        "mo_request_id": f"request-mo-{prefix}",
        "ag_request_id": f"request-ag-{prefix}",
    }


def _seed_oa(  # pragma: no cover - protected PostgreSQL evidence
    factory: Any,
    trace_id: str,
    ids: Mapping[str, str],
) -> None:
    SqlAlchemyOaAuthEventRepository(factory).record_event(
        {
            "event_type": "LOGIN_SUCCEEDED",
            "outcome": "SUCCEEDED",
            "tenant_id": ids["tenant_id"],
            "subject_id": ids["owner_id"],
            "actor_ref": f"oa.user:{ids['owner_id']}",
            "request_id": ids["oa_request_id"],
            "trace_id": trace_id,
            "details": {"auth_method": "credential"},
        }
    )


def _seed_ae(
    engine: Any,
    factory: Any,
    trace_id: str,
    ids: Mapping[str, str],
) -> None:  # pragma: no cover - protected PostgreSQL evidence
    digest = hashlib.sha256(trace_id.encode()).hexdigest()
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO ae_upload_handoffs (
                    upload_handoff_id, workspace_id, tenant_id, owner_user_id,
                    source_sha256, cx_document_id, cx_upload_id,
                    ingestion_job_id, status, record_payload, trace_id,
                    request_id, created_at, updated_at
                ) VALUES (
                    :upload, :workspace, :tenant, :owner, :digest, :document,
                    :cx_upload, :ingestion, 'READY', '{}'::jsonb, :trace,
                    :request, now(), now()
                )
                """),
            {
                "upload": ids["upload_handoff_id"],
                "workspace": f"workspace-{trace_id[:12]}",
                "tenant": ids["tenant_id"],
                "owner": ids["owner_id"],
                "digest": digest,
                "document": f"document-{trace_id[:12]}",
                "cx_upload": f"cx-upload-{trace_id[:12]}",
                "ingestion": ids["ingest_run_id"],
                "trace": trace_id,
                "request": ids["ae_request_id"],
            },
        )
        connection.execute(
            text("""
                INSERT INTO ae_artifact_handoffs (
                    artifact_handoff_id, artifact_request_id, handoff_status,
                    tenant_id, workspace_id, owner_user_id, trace_id,
                    request_id, chat_document_id, interaction_id,
                    cx_generation_id, structured_draft_id,
                    draft_schema_version,
                    structured_draft_content_hash, citation_claims_hash,
                    validation_result_hash, artifact_intent, target_formats,
                    artifact_title, language, retention_policy_ref,
                    actor_claims_ref, workspace_ref, quality_summary
                ) VALUES (
                    :handoff, :artifact_request, 'READY_FOR_RENDERING',
                    :tenant, :workspace, :owner, :trace, :request,
                    :chat_document, :interaction, :generation, :draft,
                    'cx_structured_draft.v1', :digest, :digest, :digest,
                    'create_artifact',
                    '[\"MD\"]'::jsonb, 'S138 trace artifact', 'ko',
                    's138-test', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                )
                """),
            {
                "handoff": ids["artifact_handoff_id"],
                "artifact_request": f"artifact-request-{trace_id[:12]}",
                "tenant": ids["tenant_id"],
                "workspace": f"workspace-{trace_id[:12]}",
                "owner": ids["owner_id"],
                "trace": trace_id,
                "request": ids["ae_request_id"],
                "chat_document": f"chat-document-{trace_id[:12]}",
                "interaction": f"interaction-{trace_id[:12]}",
                "generation": ids["generation_id"],
                "draft": f"draft-{trace_id[:12]}",
                "digest": digest,
            },
        )
        connection.execute(
            text("""
                INSERT INTO ae_artifacts (
                    artifact_id, artifact_type, artifact_status,
                    artifact_handoff_id, artifact_request_id, tenant_id,
                    workspace_id, owner_user_id, chat_document_id,
                    interaction_id, trace_id, request_id, display_title,
                    language, artifact_intent, target_formats,
                    retention_policy_ref, owner_actor_ref, workspace_ref,
                    template_ref, handoff_ref
                ) VALUES (
                    :artifact, 'generated_document', 'READY', :handoff,
                    :artifact_request, :tenant, :workspace, :owner,
                    :chat_document, :interaction, :trace, :request,
                    'S138 trace artifact', 'ko', 'create_artifact',
                    '[\"MD\"]'::jsonb, 's138-test', '{}'::jsonb,
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                )
                """),
            {
                "artifact": ids["artifact_id"],
                "handoff": ids["artifact_handoff_id"],
                "artifact_request": f"artifact-request-{trace_id[:12]}",
                "tenant": ids["tenant_id"],
                "workspace": f"workspace-{trace_id[:12]}",
                "owner": ids["owner_id"],
                "chat_document": f"chat-document-{trace_id[:12]}",
                "interaction": f"interaction-{trace_id[:12]}",
                "trace": trace_id,
                "request": ids["ae_request_id"],
            },
        )
    result = observe_artifact_access(
        OperationalEventEmitter(
            service_id="nex-ae-api",
            store=SqlAlchemyOperationalEventStore(factory),
        ),
        action="preview",
        artifact_file_id=ids["artifact_file_id"],
        artifact_id=ids["artifact_id"],
        allowed=True,
        request_id=ids["ae_request_id"],
        trace_id=trace_id,
    )
    if not result.ok:
        raise RuntimeError("ae_access_audit_seed_failed")


def _seed_cx(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    trace_id: str,
    ids: Mapping[str, str],
) -> None:
    digest = hashlib.sha256(trace_id.encode()).hexdigest()
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO cx_source_files (
                    source_file_id, source_sha256, size_bytes, content_type,
                    storage_uri, first_seen_trace_id, storage_backend,
                    storage_key, stored_filename, stored_extension
                ) VALUES (
                    :source_file, :digest, 1, 'text/markdown', :uri, :trace,
                    'local_filesystem', :storage_key, :stored_filename, '.md'
                )
                """),
            {
                "source_file": ids["source_file_id"],
                "digest": digest,
                "uri": f"file:///tmp/s138/{ids['source_file_id']}.md",
                "trace": trace_id,
                "storage_key": (
                    f"20261006/{digest[:2]}/{digest[2:4]}/"
                    f"{ids['source_file_id']}.md"
                ),
                "stored_filename": f"{ids['source_file_id']}.md",
            },
        )
        connection.execute(
            text("""
                INSERT INTO cx_content_objects (
                    content_object_id, tenant_id, owner_user_id,
                    source_file_id, source_sha256, upload_id,
                    original_filename, content_type, size_bytes,
                    retrieval_policy, created_trace_id, tenant_ref_type,
                    tenant_ref_id, owner_subject_ref_type,
                    owner_subject_ref_id, uploaded_by_subject_ref_type,
                    uploaded_by_subject_ref_id
                ) VALUES (
                    :content, :tenant, :owner, :source_file, :digest,
                    :upload, 's138.md', 'text/markdown', 1, '{}'::jsonb,
                    :trace, 'oa.tenant', :tenant, 'oa.user', :owner,
                    'oa.user', :owner
                )
                """),
            {
                "content": ids["content_id"],
                "tenant": ids["tenant_id"],
                "owner": ids["owner_id"],
                "source_file": ids["source_file_id"],
                "digest": digest,
                "upload": ids["upload_id"],
                "trace": trace_id,
            },
        )
        connection.execute(
            text("""
                INSERT INTO service_jobs (
                    job_id, job_type, status, trace_id, request_id,
                    subject_type, subject_id, idempotency_key,
                    attempt_count, max_attempts, retryable, links, payload,
                    available_at, completed_at, created_at, updated_at,
                    tenant_ref_type, tenant_ref_id,
                    owner_subject_ref_type, owner_subject_ref_id
                ) VALUES (
                    :job, 'cx.ingestion', 'SUCCEEDED', :trace, :request,
                    'cx.document', :content, :idempotency, 1, 3, false,
                    '{}'::jsonb, '{}'::jsonb, now(), now(), now(), now(),
                    'oa.tenant', :tenant, 'oa.user', :owner
                )
                """),
            {
                "job": ids["job_id"],
                "trace": trace_id,
                "request": ids["cx_request_id"],
                "content": ids["content_id"],
                "idempotency": f"ingest-{trace_id}",
                "tenant": ids["tenant_id"],
                "owner": ids["owner_id"],
            },
        )
        connection.execute(
            text("""
                INSERT INTO cx_ingest_runs (
                    run_id, document_id, job_id, idempotency_key, status,
                    current_step, step_states, attempt_count, max_attempts,
                    checkpoint_version, tenant_ref_id, owner_subject_ref_id,
                    trace_id, request_id, created_at, updated_at, completed_at
                ) VALUES (
                    :run, :content, :job, :idempotency, 'SUCCEEDED',
                    'summary_embedding', '{}'::jsonb, 1, 3, 1, :tenant,
                    :owner, :trace, :request, now(), now(), now()
                )
                """),
            {
                "run": ids["ingest_run_id"],
                "content": ids["content_id"],
                "job": ids["job_id"],
                "idempotency": f"ingest-{trace_id}",
                "tenant": ids["tenant_id"],
                "owner": ids["owner_id"],
                "trace": trace_id,
                "request": ids["cx_request_id"],
            },
        )
        connection.execute(
            text("""
                INSERT INTO cx_retrieval_packages (
                    retrieval_package_id, package_hash, status, trace_id,
                    request_id, query_text_sha256, purpose,
                    retrieval_policy_id, retrieval_policy_source, ranker_mix,
                    rerank_state, permission_snapshot_hash, source_summary,
                    score_summary, evidence_count, tenant_ref_type,
                    tenant_ref_id, owner_subject_ref_type,
                    owner_subject_ref_id, retrieval_runtime_schema_version,
                    persistence_payload_policy
                ) VALUES (
                    :retrieval, :digest, 'READY', :trace, :request, :digest,
                    'grounded_answer', 's138-policy', 'service_default',
                    'rrf', 'APPLIED', :digest, '{}'::jsonb, '{}'::jsonb, 1,
                    'oa.tenant', :tenant, 'oa.user', :owner,
                    'cx_retrieval_runtime.v1', 'metadata_only'
                )
                """),
            {
                "retrieval": ids["retrieval_id"],
                "digest": digest,
                "trace": trace_id,
                "request": ids["cx_request_id"],
                "tenant": ids["tenant_id"],
                "owner": ids["owner_id"],
            },
        )
        connection.execute(
            text("""
                INSERT INTO cx_generation_executions (
                    cx_generation_id, tenant_ref_type, tenant_ref_id,
                    owner_subject_ref_type, owner_subject_ref_id, status,
                    retrieval_package_id, trace_id, request_id, alias,
                    provider_capability, request_metadata, response_metadata,
                    mo_runtime_metadata, usage
                ) VALUES (
                    :generation, 'oa.tenant', :tenant, 'oa.user', :owner,
                    'COMPLETED', :retrieval, :trace, :request,
                    'generation-default', 'generation', '{}'::jsonb,
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                )
                """),
            {
                "generation": ids["generation_id"],
                "tenant": ids["tenant_id"],
                "owner": ids["owner_id"],
                "retrieval": ids["retrieval_id"],
                "trace": trace_id,
                "request": ids["cx_request_id"],
            },
        )


def _seed_mo(  # pragma: no cover - protected PostgreSQL evidence
    factory: Any,
    trace_id: str,
    ids: Mapping[str, str],
) -> None:
    result = OperationalEventEmitter(
        service_id="nex-mo",
        store=SqlAlchemyOperationalEventStore(factory),
    ).safe_emit(
        event_type="mo.provider.request.succeeded",
        severity="INFO",
        message="MO provider request succeeded.",
        trace_id=trace_id,
        request_id=ids["mo_request_id"],
        subject_ref={"type": "provider_request", "id": ids["generation_id"]},
        details={
            "provider_capability": "generation",
            "result_code": "SUCCEEDED",
            "model_alias": "generation-default",
            "provider_mode": "test",
            "provider_request_id": ids["generation_id"],
            "retryable": False,
        },
    )
    if not result.ok:
        raise RuntimeError("mo_event_seed_failed")


def _database_identities(
    engines: Mapping[str, Any],
    targets: Mapping[str, ResolvedPostgresTestTarget],
) -> dict[str, bool]:  # pragma: no cover - protected PostgreSQL evidence
    result = {}
    for service_id, engine in engines.items():
        with engine.connect() as connection:
            identity = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
        target = targets[service_id].target
        result[service_id] = tuple(identity) == (
            target.expected_database_name,
            target.expected_role_name,
        )
    return result


def _cleanup(
    engines: Mapping[str, Any],
    trace_id: str,
    ids: Mapping[str, str],
) -> dict[str, int]:  # pragma: no cover - protected PostgreSQL evidence
    with engines["nex-ag"].begin() as connection:
        connection.execute(
            text("DELETE FROM service_operational_events WHERE trace_id = :trace"),
            {"trace": trace_id},
        )
    with engines["nex-mo"].begin() as connection:
        connection.execute(
            text("DELETE FROM service_operational_events WHERE trace_id = :trace"),
            {"trace": trace_id},
        )
    with engines["nex-ae-api"].begin() as connection:
        connection.execute(
            text("DELETE FROM service_operational_events WHERE trace_id = :trace"),
            {"trace": trace_id},
        )
        connection.execute(
            text("DELETE FROM ae_artifacts WHERE artifact_id = :artifact"),
            {"artifact": ids["artifact_id"]},
        )
        connection.execute(
            text(
                "DELETE FROM ae_artifact_handoffs WHERE artifact_handoff_id = :handoff"
            ),
            {"handoff": ids["artifact_handoff_id"]},
        )
        connection.execute(
            text("DELETE FROM ae_upload_handoffs WHERE upload_handoff_id = :upload"),
            {"upload": ids["upload_handoff_id"]},
        )
    with engines["nex-cx"].begin() as connection:
        connection.execute(
            text(
                "DELETE FROM cx_generation_executions WHERE cx_generation_id = :generation"
            ),
            {"generation": ids["generation_id"]},
        )
        connection.execute(
            text(
                "DELETE FROM cx_retrieval_packages WHERE retrieval_package_id = :retrieval"
            ),
            {"retrieval": ids["retrieval_id"]},
        )
        connection.execute(
            text("DELETE FROM cx_ingest_runs WHERE run_id = :run"),
            {"run": ids["ingest_run_id"]},
        )
        connection.execute(
            text("DELETE FROM service_jobs WHERE job_id = :job"),
            {"job": ids["job_id"]},
        )
        connection.execute(
            text("DELETE FROM cx_content_objects WHERE content_object_id = :content"),
            {"content": ids["content_id"]},
        )
        connection.execute(
            text("DELETE FROM cx_source_files WHERE source_file_id = :source_file"),
            {"source_file": ids["source_file_id"]},
        )
    with engines["nex-oa"].begin() as connection:
        connection.execute(
            text("DELETE FROM oa_auth_events WHERE trace_id = :trace"),
            {"trace": trace_id},
        )
        connection.execute(
            text("DELETE FROM service_operational_events WHERE trace_id = :trace"),
            {"trace": trace_id},
        )
    return _residue(engines, trace_id)


def _residue(  # pragma: no cover - protected PostgreSQL evidence
    engines: Mapping[str, Any], trace_id: str
) -> dict[str, int]:
    queries = {
        "nex-oa": "SELECT count(*) FROM oa_auth_events WHERE trace_id = :trace",
        "nex-ae-api": (
            "SELECT count(*) FROM ae_upload_handoffs WHERE trace_id = :trace"
        ),
        "nex-cx": "SELECT count(*) FROM cx_ingest_runs WHERE trace_id = :trace",
        "nex-mo": (
            "SELECT count(*) FROM service_operational_events WHERE trace_id = :trace"
        ),
        "nex-ag": (
            "SELECT count(*) FROM service_operational_events WHERE trace_id = :trace"
        ),
    }
    result = {}
    for service_id, statement in queries.items():
        with engines[service_id].connect() as connection:
            result[service_id] = int(
                connection.execute(text(statement), {"trace": trace_id}).scalar_one()
            )
    return result


def _failure(code: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1380",
        "requirement": "S138",
        "status": "FAIL",
        "failure_code": code[:160],
        "actual_postgresql": False,
        "next_slice": "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    if result.get("status") == "SKIPPED":
        return f"platform_ag_trace_postgres_smoke=skipped reason={result.get('skip_reason')}"
    return (
        "platform_ag_trace_postgres_smoke="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"services={summary.get('service_count', 0)} "
        f"families={summary.get('stage_family_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_ag_trace_postgres_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
