#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
SMOKE_PATH = ROOT / "scripts" / "smoke"
AE_PATH = ROOT / "services" / "nex-ae-api"
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(SMOKE_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(CX_PATH))

from nex_ae_api.auth_sessions import AUTH_SESSION_MODE_OA  # noqa: E402
from nex_ae_api.uploads import (  # noqa: E402
    UPLOAD_OWNER_RESOLVER_DISABLED,
    UploadHandoffStore,
    register_upload_routes,
)
from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    UPLOAD_OWNER_RESOLVER_VERIFY,
    register_ingestion_routes,
)
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_runtime import load_env_file  # noqa: E402
from run_ae_web_same_origin_runtime_boundary import PROXY_TARGET_ENV  # noqa: E402
from run_ae_web_same_origin_runtime_boundary import (  # noqa: E402
    run_ae_web_same_origin_runtime_boundary,
)
from run_ae_web_playwright_readiness import (  # noqa: E402
    run_ae_web_playwright_readiness,
)
import run_ae_web_credential_login_playwright_postgres_smoke as login_pg  # noqa: E402


base_auth = login_pg.base_auth

SCHEMA_VERSION = "ae_web_authenticated_upload_playwright_postgres_smoke.v1"
NODE_SMOKE_SCHEMA_VERSION = "ae_web_authenticated_upload_playwright_smoke.v1"
SMOKE_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE"
PROFILE_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_PROFILE"
TENANT_ID_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_TENANT_ID"
SUBJECT_ID_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SUBJECT_ID"
EMPLOYEE_ID_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_EMPLOYEE_ID"
PASSWORD_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_PASSWORD"
FILENAME_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_FILENAME"
CONTENT_TYPE_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_CONTENT_TYPE"
SIZE_BYTES_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SIZE_BYTES"
SOURCE_SHA256_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SOURCE_SHA256"
CHROMIUM_EXECUTABLE_ENV = "NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE"
TIMEOUT_MS_ENV = "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_TIMEOUT_MS"
DEFAULT_PROFILE = "test"
DEFAULT_PASSWORD = "Nuri1004!"
DEFAULT_CONTENT_TYPE = "text/markdown"
DEFAULT_SIZE_BYTES = 1536
DEFAULT_UPLOAD_BYTE = b"n"
CX_SERVICE_ID = "nex-cx"
CX_SERVICE_SPEC = base_auth.SERVICE_SPECS[CX_SERVICE_ID]
WEB_ROOT = ROOT / "apps" / "nex-ae-web"
NODE_SMOKE_SCRIPT = WEB_ROOT / "scripts" / "runAuthenticatedUploadPlaywrightSmoke.mjs"

ProtectedRunner = Callable[[dict[str, str]], dict[str, Any]]
NodeRunner = Callable[..., dict[str, Any]]
PortAllocator = Callable[[], int]

PROTECTED_ENV_KEYS = (
    base_auth.service_database_env(base_auth.AE_SERVICE_ID, profile=DEFAULT_PROFILE),
    base_auth.service_database_env(base_auth.OA_SERVICE_ID, profile=DEFAULT_PROFILE),
    base_auth.service_database_env(CX_SERVICE_ID, profile=DEFAULT_PROFILE),
    TENANT_ID_ENV,
    SUBJECT_ID_ENV,
    EMPLOYEE_ID_ENV,
    PASSWORD_ENV,
    SOURCE_SHA256_ENV,
    PROXY_TARGET_ENV,
)


@dataclass
class TestClientCxUploadClient:
    client: TestClient
    calls: list[dict[str, object]] = field(default_factory=list)

    def register_upload(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/documents/uploads",
            headers=_cx_service_headers(trace_id=trace_id, request_id=request_id),
            json=payload,
        )
        body = _safe_response_json(response)
        self.calls.append(
            {
                "operation": "register_upload",
                "status_code": response.status_code,
                "dedupe_status": _mapping(body.get("dedupe")).get("status"),
            }
        )
        response.raise_for_status()
        return body


@dataclass
class StaticOwnerResolver:
    calls: list[dict[str, object]] = field(default_factory=list)

    def resolve_ownership_ref(
        self,
        ownership_ref: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
        ensure: bool = False,
    ) -> dict[str, object]:
        normalized = dict(ownership_ref)
        self.calls.append(
            {
                "ownership_ref": normalized,
                "request_id": request_id,
                "trace_id": trace_id,
                "ensure": ensure,
            }
        )
        return {
            "resolver_schema_version": "oa_subject_registry_resolver.v1",
            "resolution_status": "RESOLVED",
            "action": "verify",
            "tenant_ref": dict(normalized["tenant_ref"]),
            "owner_subject_ref": dict(normalized["owner_subject_ref"]),
            "uploaded_by_subject_ref": dict(normalized["uploaded_by_subject_ref"]),
        }


@dataclass
class PreparedAuthenticatedUploadPlaywrightPostgresSmoke:
    profile: str
    request_id: str
    trace_id: str
    tenant_id: str
    subject_id: str
    employee_id: str
    password: str
    filename: str
    content_type: str
    size_bytes: int
    source_sha256: str
    database_envs: dict[str, str]
    redacted_database_urls: dict[str, str]
    migrations: dict[str, dict[str, object]]
    ae_engine: Any
    oa_engine: Any
    cx_engine: Any
    ae_app: Any
    ae_marker_id: str | None
    cx_upload_client: TestClientCxUploadClient
    cx_owner_resolver: StaticOwnerResolver
    storage_tempdir: tempfile.TemporaryDirectory[str]

    def cleanup(self, *, session_id: str | None) -> dict[str, Any]:
        cleanup = {
            "ae_marker_rows_after_delete": base_auth._delete_ae_smoke_marker(
                self.ae_engine,
                event_id=self.ae_marker_id,
            ),
            "oa_rows": base_auth._delete_oa_smoke_rows(
                self.oa_engine,
                tenant_id=self.tenant_id,
                subject_id=self.subject_id,
                employee_id=self.employee_id,
                session_id=session_id,
            ),
            "cx_rows": _delete_cx_smoke_rows(
                self.cx_engine,
                tenant_id=self.tenant_id,
                owner_user_id=self.subject_id,
                source_sha256=self.source_sha256,
            ),
        }
        self.storage_tempdir.cleanup()
        return cleanup


def run_ae_web_authenticated_upload_playwright_postgres_smoke(
    environ: dict[str, str] | None = None,
    *,
    readiness_runner: ProtectedRunner = run_ae_web_playwright_readiness,
    boundary_runner: ProtectedRunner = run_ae_web_same_origin_runtime_boundary,
    prepare_runner: Callable[
        [dict[str, str], str],
        PreparedAuthenticatedUploadPlaywrightPostgresSmoke,
    ] = lambda env, profile: prepare_playwright_upload_postgres_smoke(
        env,
        profile=profile,
    ),
    node_runner: NodeRunner | None = None,
    session_observer: Callable[..., dict[str, Any]] | None = None,
    cx_observer: Callable[..., dict[str, Any]] | None = None,
    port_allocator: PortAllocator | None = None,
    api_server_starter: Callable[[Any, int], login_pg.StartedServer] | None = None,
    web_server_starter: Callable[[int, str], login_pg.StartedServer] | None = None,
) -> dict[str, Any]:
    node_runner = node_runner or run_node_playwright_upload_smoke
    session_observer = session_observer or login_pg.latest_session_observations
    cx_observer = cx_observer or latest_cx_upload_observations
    port_allocator = port_allocator or login_pg.find_free_port
    api_server_starter = api_server_starter or login_pg.start_api_server
    web_server_starter = web_server_starter or login_pg.start_web_server
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        }

    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", profile=profile, env=env)

    readiness = readiness_runner(env)
    if readiness["status"] != "PASS":
        return _failure("readiness_failed", profile=profile, env=env, readiness=readiness)

    prepared: PreparedAuthenticatedUploadPlaywrightPostgresSmoke | None = None
    api_server: login_pg.StartedServer | None = None
    web_server: login_pg.StartedServer | None = None
    evidence: dict[str, Any] | None = None
    session_observations: dict[str, Any] = {}
    cx_observations: dict[str, Any] = {}
    try:
        prepared = prepare_runner(dict(env), profile)
        api_port = port_allocator()
        web_port = port_allocator()
        api_server = api_server_starter(prepared.ae_app, api_port)
        web_server = web_server_starter(web_port, api_server.url)
        boundary_env = {**env, PROXY_TARGET_ENV: api_server.url}
        boundary = boundary_runner(boundary_env)
        if boundary["status"] != "PASS":
            return _failure(
                "same_origin_boundary_failed",
                profile=profile,
                env=boundary_env,
                readiness=readiness,
                boundary=boundary,
            )
        node_env = _node_environ(
            env,
            web_url=web_server.url,
            tenant_id=prepared.tenant_id,
            employee_id=prepared.employee_id,
            password=prepared.password,
            filename=prepared.filename,
            content_type=prepared.content_type,
            size_bytes=prepared.size_bytes,
            source_sha256=prepared.source_sha256,
        )
        node_smoke = node_runner(node_env)
        session_observations = session_observer(
            prepared.oa_engine,
            tenant_id=prepared.tenant_id,
            subject_id=prepared.subject_id,
        )
        cx_observations = cx_observer(
            prepared.cx_engine,
            tenant_id=prepared.tenant_id,
            owner_user_id=prepared.subject_id,
            source_sha256=prepared.source_sha256,
        )
        evidence = _pass_or_fail_evidence(
            profile=profile,
            env={**env, PROXY_TARGET_ENV: api_server.url},
            readiness=readiness,
            boundary=boundary,
            prepared=prepared,
            node_smoke=node_smoke,
            session_observations=session_observations,
            cx_observations=cx_observations,
        )
        return evidence
    except (base_auth.MigrationError, ValueError) as exc:
        return _failure(
            "configuration_invalid",
            profile=profile,
            env=env,
            detail=exc.__class__.__name__,
        )
    except Exception as exc:
        return _failure(
            "execution_failed",
            profile=profile,
            env=env,
            detail=exc.__class__.__name__,
        )
    finally:
        if web_server is not None:
            web_server.stop()
        if api_server is not None:
            api_server.stop()
        if prepared is not None:
            cleanup_observations = prepared.cleanup(
                session_id=session_observations.get("session_id")
            )
            if cleanup_observations and evidence is not None:
                evidence["cleanup_observations"] = cleanup_observations


def prepare_playwright_upload_postgres_smoke(
    env: dict[str, str],
    *,
    profile: str,
) -> PreparedAuthenticatedUploadPlaywrightPostgresSmoke:  # pragma: no cover
    database_envs = {
        "ae": base_auth.service_database_env(base_auth.AE_SERVICE_ID, profile=profile),
        "oa": base_auth.service_database_env(base_auth.OA_SERVICE_ID, profile=profile),
        "cx": base_auth.service_database_env(CX_SERVICE_ID, profile=profile),
    }
    database_urls = {
        "ae": base_auth.service_database_url(
            base_auth.AE_SERVICE_ID,
            profile=profile,
            environ=env,
        ),
        "oa": base_auth.service_database_url(
            base_auth.OA_SERVICE_ID,
            profile=profile,
            environ=env,
        ),
        "cx": base_auth.service_database_url(
            CX_SERVICE_ID,
            profile=profile,
            environ=env,
        ),
    }
    for service_key, database_url in database_urls.items():
        base_auth._require_test_database_url(
            database_url,
            env_name=database_envs[service_key],
        )
    migrations = {
        "ae": base_auth._migration_evidence(
            base_auth.run_service_migrations(
                base_auth.AE_SERVICE_ID,
                database_url=database_urls["ae"],
                profile=profile,
            )
        ),
        "oa": base_auth._migration_evidence(
            base_auth.run_service_migrations(
                base_auth.OA_SERVICE_ID,
                database_url=database_urls["oa"],
                profile=profile,
            )
        ),
        "cx": base_auth._migration_evidence(
            base_auth.run_service_migrations(
                CX_SERVICE_ID,
                database_url=database_urls["cx"],
                profile=profile,
            )
        ),
    }
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.split("-", maxsplit=1)[0]
    tenant_id = env.get(TENANT_ID_ENV) or f"tenant-ae-web-upload-{suffix}"
    subject_id = env.get(SUBJECT_ID_ENV) or f"user-ae-web-upload-{suffix}"
    employee_id = env.get(EMPLOYEE_ID_ENV) or f"EMP-AE-WEB-UP-{suffix}"
    password = env.get(PASSWORD_ENV) or DEFAULT_PASSWORD
    filename = env.get(FILENAME_ENV) or f"slice-0274-upload-{suffix}.md"
    content_type = env.get(CONTENT_TYPE_ENV) or DEFAULT_CONTENT_TYPE
    size_bytes = _bounded_size_bytes(env.get(SIZE_BYTES_ENV))
    source_sha256 = _source_sha256_for_upload_bytes(
        size_bytes,
        explicit_value=env.get(SOURCE_SHA256_ENV),
    )
    storage_tempdir = tempfile.TemporaryDirectory(
        prefix="nex-ae-web-upload-playwright-smoke-"
    )
    ae_engine = base_auth.build_engine(database_urls["ae"])
    oa_engine = base_auth.build_engine(database_urls["oa"])
    cx_engine = base_auth.build_engine(database_urls["cx"])
    ae_marker_id = base_auth._write_ae_smoke_marker(
        ae_engine,
        request_id=request_id,
        trace_id=trace_id,
        subject_id=subject_id,
    )
    try:
        oa_app = login_pg.build_oa_app(
            env=env,
            oa_database_url=database_urls["oa"],
            trace_id=trace_id,
            request_id=request_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            employee_id=employee_id,
            password=password,
        )
        oa_client = TestClient(oa_app)
        oa_session_client = base_auth.TestClientOaUserSessionClient(oa_client)
        cx_owner_resolver = StaticOwnerResolver()
        cx_app = build_cx_app(
            env=env,
            cx_database_url=database_urls["cx"],
            storage_root=Path(storage_tempdir.name),
            owner_resolver=cx_owner_resolver,
        )
        cx_upload_client = TestClientCxUploadClient(TestClient(cx_app))
        ae_app = build_ae_app(
            env=env,
            ae_database_url=database_urls["ae"],
            oa_session_client=oa_session_client,
            cx_upload_client=cx_upload_client,
        )
        return PreparedAuthenticatedUploadPlaywrightPostgresSmoke(
            profile=profile,
            request_id=request_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            employee_id=employee_id,
            password=password,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            source_sha256=source_sha256,
            database_envs=database_envs,
            redacted_database_urls={
                key: base_auth.redact_database_url(value)
                for key, value in database_urls.items()
            },
            migrations=migrations,
            ae_engine=ae_engine,
            oa_engine=oa_engine,
            cx_engine=cx_engine,
            ae_app=ae_app,
            ae_marker_id=ae_marker_id,
            cx_upload_client=cx_upload_client,
            cx_owner_resolver=cx_owner_resolver,
            storage_tempdir=storage_tempdir,
        )
    except Exception:
        base_auth._delete_ae_smoke_marker(ae_engine, event_id=ae_marker_id)
        base_auth._delete_oa_smoke_rows(
            oa_engine,
            tenant_id=tenant_id,
            subject_id=subject_id,
            employee_id=employee_id,
            session_id=None,
        )
        _delete_cx_smoke_rows(
            cx_engine,
            tenant_id=tenant_id,
            owner_user_id=subject_id,
            source_sha256=source_sha256,
        )
        storage_tempdir.cleanup()
        raise


def build_cx_app(
    *,
    env: Mapping[str, str],
    cx_database_url: str,
    storage_root: Path,
    owner_resolver: StaticOwnerResolver,
) -> Any:  # pragma: no cover
    cx_app = base_auth.build_service_app(CX_SERVICE_SPEC)
    cx_persistence = base_auth.attach_service_persistence_runtime(
        cx_app,
        CX_SERVICE_SPEC,
        environ={
            **env,
            CX_SERVICE_SPEC.database_env: cx_database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
            "NEX_CX_UPLOAD_OWNER_RESOLVER_MODE": UPLOAD_OWNER_RESOLVER_VERIFY,
        },
    )
    if cx_persistence.api_session_factory is None:
        raise RuntimeError("CX PostgreSQL session factory is unavailable")
    storage_config = _storage_config(storage_root)
    repository = SqlAlchemyCxContentRepository(
        cx_persistence.api_session_factory,
        local_source_root=storage_config.source_root,
    )
    register_ingestion_routes(
        cx_app,
        store=ContentIngestionStore(content_repository=repository),
        storage_config=storage_config,
        owner_resolver=owner_resolver,
        owner_resolver_mode=UPLOAD_OWNER_RESOLVER_VERIFY,
    )
    return cx_app


def build_ae_app(
    *,
    env: Mapping[str, str],
    ae_database_url: str,
    oa_session_client: Any,
    cx_upload_client: TestClientCxUploadClient,
) -> Any:  # pragma: no cover
    ae_app = base_auth.build_service_app(base_auth.AE_SERVICE_SPEC)
    ae_persistence = base_auth.attach_service_persistence_runtime(
        ae_app,
        base_auth.AE_SERVICE_SPEC,
        environ={
            **env,
            base_auth.AE_SERVICE_SPEC.database_env: ae_database_url,
            "NEX_AE_PERSISTENCE_MODE": "postgres",
        },
    )
    if ae_persistence.api_session_factory is None:
        raise RuntimeError("AE PostgreSQL session factory is unavailable")
    base_auth.register_auth_session_routes(
        ae_app,
        oa_session_client=oa_session_client,
        session_mode=AUTH_SESSION_MODE_OA,
    )
    register_upload_routes(
        ae_app,
        store=UploadHandoffStore(),
        cx_client=cx_upload_client,
        owner_resolver_mode=UPLOAD_OWNER_RESOLVER_DISABLED,
        oa_session_client=oa_session_client,
        session_mode=AUTH_SESSION_MODE_OA,
    )
    return ae_app


def run_node_playwright_upload_smoke(env: Mapping[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["node", str(NODE_SMOKE_SCRIPT)],
        cwd=ROOT,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        if completed.returncode != 0:
            return {
                "smoke_schema_version": NODE_SMOKE_SCHEMA_VERSION,
                "status": "FAIL",
                "failure_code": "node_playwright_failed",
                "returncode": completed.returncode,
            }
        return {
            "smoke_schema_version": NODE_SMOKE_SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "node_json_invalid",
            "returncode": completed.returncode,
        }
    if isinstance(payload, dict):
        payload.setdefault("returncode", completed.returncode)
        return payload
    return {
        "smoke_schema_version": NODE_SMOKE_SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "node_payload_invalid",
    }


def latest_cx_upload_observations(
    engine: Any,
    *,
    tenant_id: str,
    owner_user_id: str,
    source_sha256: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        content_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM cx_content_objects
                WHERE tenant_ref_id = :tenant_id
                  AND owner_subject_ref_id = :owner_user_id
                  AND source_sha256 = :source_sha256
                """
            ),
            {
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
                "source_sha256": source_sha256,
            },
        ).scalar_one()
        source_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM cx_source_files
                WHERE source_sha256 = :source_sha256
                """
            ),
            {"source_sha256": source_sha256},
        ).scalar_one()
        row = connection.execute(
            text(
                """
                SELECT
                    co.content_object_id,
                    co.source_file_id,
                    co.lifecycle_status,
                    co.tenant_ref_type,
                    co.tenant_ref_id,
                    co.owner_subject_ref_type,
                    co.owner_subject_ref_id,
                    co.uploaded_by_subject_ref_type,
                    co.uploaded_by_subject_ref_id,
                    co.source_sha256,
                    sf.storage_backend,
                    sf.checksum_verified_at
                FROM cx_content_objects co
                JOIN cx_source_files sf ON sf.source_file_id = co.source_file_id
                WHERE co.tenant_ref_id = :tenant_id
                  AND co.owner_subject_ref_id = :owner_user_id
                  AND co.source_sha256 = :source_sha256
                ORDER BY co.created_at DESC
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
                "source_sha256": source_sha256,
            },
        ).mappings().first()
    if row is None:
        return {
            "document_id": None,
            "source_file_id": None,
            "content_object_count": int(content_count),
            "source_file_count": int(source_count),
            "owner_refs_match": False,
            "source_sha256_present": False,
            "checksum_verified_at_present": False,
            "storage_backend": None,
            "lifecycle_status": None,
        }
    return {
        "document_id": row["content_object_id"],
        "source_file_id": row["source_file_id"],
        "content_object_count": int(content_count),
        "source_file_count": int(source_count),
        "owner_refs_match": (
            row["tenant_ref_type"] == "oa.tenant"
            and row["tenant_ref_id"] == tenant_id
            and row["owner_subject_ref_type"] == "oa.user"
            and row["owner_subject_ref_id"] == owner_user_id
            and row["uploaded_by_subject_ref_type"] == "oa.user"
            and row["uploaded_by_subject_ref_id"] == owner_user_id
        ),
        "source_sha256_present": row["source_sha256"] == source_sha256,
        "checksum_verified_at_present": row["checksum_verified_at"] is not None,
        "storage_backend": row["storage_backend"],
        "lifecycle_status": row["lifecycle_status"],
    }


def _pass_or_fail_evidence(
    *,
    profile: str,
    env: Mapping[str, str],
    readiness: Mapping[str, Any],
    boundary: Mapping[str, Any],
    prepared: PreparedAuthenticatedUploadPlaywrightPostgresSmoke,
    node_smoke: Mapping[str, Any],
    session_observations: Mapping[str, Any],
    cx_observations: Mapping[str, Any],
) -> dict[str, Any]:
    node_checks = _mapping(node_smoke.get("checks"))
    cx_public = _public_cx_observations(cx_observations)
    checks = {
        "readiness_passed": readiness.get("status") == "PASS",
        "same_origin_boundary_passed": boundary.get("status") == "PASS",
        "node_playwright_smoke_passed": node_smoke.get("status") == "PASS",
        "playwright_browser_launched": (
            node_checks.get("playwright_browser_launched") is True
        ),
        "same_origin_login_called": node_checks.get("same_origin_login_called") is True,
        "same_origin_upload_called": node_checks.get("same_origin_upload_called") is True,
        "same_origin_logout_called": node_checks.get("same_origin_logout_called") is True,
        "upload_response_accepted": (
            node_checks.get("upload_response_accepted") is True
        ),
        "browser_upload_feedback_accepted": (
            node_checks.get("upload_feedback_accepted") is True
        ),
        "browser_upload_body_multipart": (
            node_checks.get("upload_body_multipart") is True
        ),
        "browser_upload_multipart_content_type_present": (
            node_checks.get("upload_multipart_content_type_present") is True
        ),
        "browser_upload_multipart_body_shape_safe": (
            node_checks.get("upload_multipart_body_shape_safe") is True
        ),
        "browser_upload_multipart_fields_present_when_introspected": (
            node_checks.get("upload_multipart_fields_present_when_introspected")
            is True
        ),
        "browser_upload_body_not_serialized_in_evidence": (
            node_checks.get("upload_body_not_serialized_in_evidence") is True
        ),
        "ae_test_database_connected": (
            base_auth._count_ae_marker_rows(
                prepared.ae_engine,
                event_id=prepared.ae_marker_id,
            )
            == 1
        ),
        "oa_membership_persisted": session_observations.get("membership_count") == 1,
        "oa_credential_persisted": session_observations.get("credential_count") == 1,
        "oa_session_persisted": session_observations.get("session_count") == 1,
        "oa_session_revoked": (
            session_observations.get("session_status") == "REVOKED"
            and session_observations.get("session_revoked_at_present") is True
        ),
        "oa_session_subject_matches": (
            session_observations.get("session_subject_matches") is True
        ),
        "cx_content_object_persisted": cx_observations.get("content_object_count") == 1,
        "cx_source_file_persisted": cx_observations.get("source_file_count") == 1,
        "cx_owner_refs_match": cx_observations.get("owner_refs_match") is True,
        "cx_source_sha256_persisted": (
            cx_observations.get("source_sha256_present") is True
        ),
        "cx_source_checksum_verified": (
            cx_observations.get("checksum_verified_at_present") is True
        ),
        "cx_storage_backend_local": (
            cx_observations.get("storage_backend") == "local_filesystem"
        ),
        "cx_lifecycle_active": cx_observations.get("lifecycle_status") == "ACTIVE",
        "cx_upload_client_called_once": len(prepared.cx_upload_client.calls) == 1,
        "cx_owner_resolver_verified_once": len(prepared.cx_owner_resolver.calls) == 1,
        "redacted_evidence": True,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "profile": profile,
        "services": [
            "nex-ae-web",
            base_auth.AE_SERVICE_ID,
            base_auth.OA_SERVICE_ID,
            CX_SERVICE_ID,
        ],
        "source_smokes": {
            "playwright_readiness": {
                "schema_version": readiness.get("readiness_schema_version"),
                "status": readiness.get("status"),
            },
            "same_origin_boundary": {
                "schema_version": boundary.get("boundary_schema_version"),
                "status": boundary.get("status"),
            },
            "node_playwright": {
                "schema_version": node_smoke.get("smoke_schema_version"),
                "status": node_smoke.get("status"),
                "failure_code": node_smoke.get("failure_code"),
            },
        },
        "database_envs": prepared.database_envs,
        "redacted_database_urls": prepared.redacted_database_urls,
        "migrations": prepared.migrations,
        "request_id": prepared.request_id,
        "trace_id": prepared.trace_id,
        "browser_observations": _mapping(node_smoke.get("browser_observations")),
        "request_observations": _public_request_observations(
            _mapping(node_smoke.get("request_observations"))
        ),
        "db_observations": {
            "ae_marker_rows": 1 if checks["ae_test_database_connected"] else 0,
            "oa_membership_count": session_observations.get("membership_count", 0),
            "oa_credential_count": session_observations.get("credential_count", 0),
            "oa_session_count": session_observations.get("session_count", 0),
            "oa_session_status": session_observations.get("session_status"),
            "oa_session_revoked_at_present": session_observations.get(
                "session_revoked_at_present",
                False,
            ),
            "cx": cx_public,
        },
        "upload_observations": {
            "filename_present": bool(prepared.filename),
            "content_type": prepared.content_type,
            "size_bytes": prepared.size_bytes,
            "source_sha256_present": True,
            "browser_source_bytes_sent": True,
            "cx_adapter_status_code": prepared.cx_upload_client.calls[0]["status_code"]
            if prepared.cx_upload_client.calls
            else None,
            "cx_adapter_dedupe_status": prepared.cx_upload_client.calls[0][
                "dedupe_status"
            ]
            if prepared.cx_upload_client.calls
            else None,
        },
        "checks": checks,
        "issues": [
            {"category": "check_failed", "subject": name}
            for name, passed in checks.items()
            if not passed
        ],
        "redaction": {
            "raw_password_in_evidence": False,
            "raw_source_in_evidence": False,
            "cookie_material_in_evidence": False,
            "credential_material_in_evidence": False,
            "database_endpoint_in_evidence": False,
            "provider_endpoint_in_evidence": False,
        },
    }
    assert_smoke_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def _failure(
    failure_code: str,
    *,
    profile: str,
    env: Mapping[str, str],
    detail: str | None = None,
    readiness: Mapping[str, Any] | None = None,
    boundary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
        "source_smokes": {
            "playwright_readiness": _source_status(
                readiness,
                version_key="readiness_schema_version",
            ),
            "same_origin_boundary": _source_status(
                boundary,
                version_key="boundary_schema_version",
            ),
        },
        "checks": {
            "redacted_evidence": True,
        },
    }
    assert_smoke_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def _node_environ(
    env: Mapping[str, str],
    *,
    web_url: str,
    tenant_id: str,
    employee_id: str,
    password: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    source_sha256: str,
) -> dict[str, str]:
    node_env = {
        "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_WEB_URL": web_url,
        "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_TENANT_ID": tenant_id,
        "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_EMPLOYEE_ID": employee_id,
        "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_PASSWORD": password,
        "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_FILENAME": filename,
        "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_CONTENT_TYPE": content_type,
        "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SIZE_BYTES": str(size_bytes),
        "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SOURCE_SHA256": source_sha256,
    }
    if env.get(CHROMIUM_EXECUTABLE_ENV):
        node_env[CHROMIUM_EXECUTABLE_ENV] = env[CHROMIUM_EXECUTABLE_ENV]
    if env.get(TIMEOUT_MS_ENV):
        node_env[TIMEOUT_MS_ENV] = env[TIMEOUT_MS_ENV]
    return node_env


def _public_request_observations(observations: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ae_api_request_count": observations.get("ae_api_request_count", 0),
        "ae_api_response_count": observations.get("ae_api_response_count", 0),
        "request_routes": observations.get("request_routes", []),
        "response_routes": observations.get("response_routes", []),
        "upload_response_status": observations.get("upload_response_status"),
    }


def _public_cx_observations(observations: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "content_object_count": observations.get("content_object_count", 0),
        "source_file_count": observations.get("source_file_count", 0),
        "document_id_present": bool(observations.get("document_id")),
        "source_file_id_present": bool(observations.get("source_file_id")),
        "owner_refs_match": observations.get("owner_refs_match") is True,
        "source_sha256_present": observations.get("source_sha256_present") is True,
        "checksum_verified_at_present": observations.get(
            "checksum_verified_at_present"
        )
        is True,
        "storage_backend": observations.get("storage_backend"),
        "lifecycle_status": observations.get("lifecycle_status"),
    }


def _delete_cx_smoke_rows(
    engine: Any,
    *,
    tenant_id: str,
    owner_user_id: str,
    source_sha256: str,
) -> dict[str, int]:
    with engine.begin() as connection:
        source_file_ids = [
            row["source_file_id"]
            for row in connection.execute(
                text(
                    """
                    SELECT DISTINCT co.source_file_id
                    FROM cx_content_objects co
                    WHERE co.tenant_ref_id = :tenant_id
                      AND co.owner_subject_ref_id = :owner_user_id
                      AND co.source_sha256 = :source_sha256
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "owner_user_id": owner_user_id,
                    "source_sha256": source_sha256,
                },
            ).mappings()
            if row["source_file_id"] is not None
        ]
        deleted_acl = connection.execute(
            text(
                """
                DELETE FROM cx_content_acl_entries
                WHERE content_object_id IN (
                    SELECT content_object_id
                    FROM cx_content_objects
                    WHERE tenant_ref_id = :tenant_id
                      AND owner_subject_ref_id = :owner_user_id
                      AND source_sha256 = :source_sha256
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
                "source_sha256": source_sha256,
            },
        ).rowcount
        deleted_content = connection.execute(
            text(
                """
                DELETE FROM cx_content_objects
                WHERE tenant_ref_id = :tenant_id
                  AND owner_subject_ref_id = :owner_user_id
                  AND source_sha256 = :source_sha256
                """
            ),
            {
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
                "source_sha256": source_sha256,
            },
        ).rowcount
        source_file_ids.extend(
            row["source_file_id"]
            for row in connection.execute(
                text(
                    """
                    SELECT source_file_id
                    FROM cx_source_files
                    WHERE source_sha256 = :source_sha256
                    """
                ),
                {"source_sha256": source_sha256},
            ).mappings()
            if row["source_file_id"] is not None
        )
        deleted_sources = 0
        for source_file_id in sorted(set(source_file_ids)):
            remaining = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_content_objects
                    WHERE source_file_id = :source_file_id
                    """
                ),
                {"source_file_id": source_file_id},
            ).scalar_one()
            if int(remaining) == 0:
                deleted_sources += int(
                    connection.execute(
                        text(
                            """
                            DELETE FROM cx_source_files
                            WHERE source_file_id = :source_file_id
                            """
                        ),
                        {"source_file_id": source_file_id},
                    ).rowcount
                    or 0
                )
    return {
        "deleted_acl_entries": int(deleted_acl or 0),
        "deleted_content_objects": int(deleted_content or 0),
        "deleted_source_files": deleted_sources,
    }


def _storage_config(temp_dir: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=temp_dir,
        source_root=temp_dir / "cx" / "source-files",
        extracted_markdown_root=temp_dir / "cx" / "extracted-markdown",
        extraction_temp_root=temp_dir / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def _cx_service_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = base_auth.issue_mock_service_token(
        service_id=base_auth.AE_SERVICE_ID,
        audience=CX_SERVICE_ID,
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-Service-ID": base_auth.AE_SERVICE_ID,
    }


def _bounded_size_bytes(raw_value: str | None) -> int:
    if raw_value is None:
        return DEFAULT_SIZE_BYTES
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{SIZE_BYTES_ENV} must be an integer.") from exc
    if value < 0 or value > 2 * 1024 * 1024:
        raise ValueError(f"{SIZE_BYTES_ENV} must be between 0 and 2097152.")
    return value


def _deterministic_upload_source_sha256(size_bytes: int) -> str:
    return hashlib.sha256(DEFAULT_UPLOAD_BYTE * size_bytes).hexdigest()


def _source_sha256_for_upload_bytes(
    size_bytes: int,
    *,
    explicit_value: str | None,
) -> str:
    computed = _deterministic_upload_source_sha256(size_bytes)
    if explicit_value is None:
        return computed
    supplied = _valid_sha256(explicit_value)
    if supplied != computed:
        raise ValueError(
            f"{SOURCE_SHA256_ENV} must match the deterministic smoke file bytes."
        )
    return supplied


def _valid_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized):
        return normalized
    raise ValueError(f"{SOURCE_SHA256_ENV} must be a 64-character hex string.")


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    leaked = [
        key
        for key in PROTECTED_ENV_KEYS
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked:
        raise ValueError(
            "AE Web authenticated upload Playwright PostgreSQL smoke evidence "
            f"contains unredacted environment value: {leaked[0]}"
        )


def _protected_env_value_leaked(serialized: str, value: str | None) -> bool:
    return bool(value and value not in {DEFAULT_PROFILE, "1"} and value in serialized)


def _source_status(
    evidence: Mapping[str, Any] | None,
    *,
    version_key: str,
) -> dict[str, Any]:
    if evidence is None:
        return {"status": "NOT_RUN"}
    source = {"status": evidence.get("status", "UNKNOWN")}
    if version_key in evidence:
        source["schema_version"] = evidence.get(version_key)
    return source


def _safe_response_json(response: object) -> dict[str, Any]:
    try:
        payload = response.json()
    except (AttributeError, json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def write_smoke_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_smoke_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_web_authenticated_upload_playwright_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        db = _mapping(evidence.get("db_observations"))
        browser = _mapping(evidence.get("browser_observations"))
        cx = _mapping(db.get("cx"))
        return (
            "ae_web_authenticated_upload_playwright_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"upload={browser.get('upload_feedback_status')} "
            f"cx_content={cx.get('content_object_count')} "
            f"cx_checksum={'verified' if cx.get('checksum_verified_at_present') else 'pending'} "
            f"oa_session_status={db.get('oa_session_status')} "
            "live_db=true browser=playwright"
        )
    return (
        "ae_web_authenticated_upload_playwright_postgres_smoke=fail "
        f"reason={evidence.get('failure_code', 'checks_failed')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run protected AE Web Playwright upload PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_env_file(ROOT / ".env.local")
        evidence = run_ae_web_authenticated_upload_playwright_postgres_smoke()
        if args.output:
            write_smoke_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        )
        return 1 if evidence["status"] == "FAIL" else 0
    except ValueError as exc:
        print(
            "ae_web_authenticated_upload_playwright_postgres_smoke=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
