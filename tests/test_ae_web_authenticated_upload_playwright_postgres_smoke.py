from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

import run_ae_web_authenticated_upload_playwright_postgres_smoke as smoke


class FakePrepared:
    profile = "test"
    request_id = "request-0274"
    trace_id = "trace0274"
    tenant_id = "tenant-upload-0274"
    subject_id = "user-upload-0274"
    employee_id = "EMP-UPLOAD-0274"
    password = "playwright-upload-secret-0274"
    filename = "slice-0274-upload.md"
    content_type = "text/markdown"
    size_bytes = 1536
    source_sha256 = smoke._deterministic_upload_source_sha256(size_bytes)
    database_envs = {
        "ae": "NEX_AE_TEST_DATABASE_URL",
        "oa": "NEX_OA_TEST_DATABASE_URL",
        "cx": "NEX_CX_TEST_DATABASE_URL",
    }
    redacted_database_urls = {
        "ae": "postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test",
        "oa": "postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test",
        "cx": "postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test",
    }
    migrations = {
        "ae": {"service_id": "nex-ae-api", "profile": "test"},
        "oa": {"service_id": "nex-oa", "profile": "test"},
        "cx": {"service_id": "nex-cx", "profile": "test"},
    }
    ae_engine = object()
    oa_engine = object()
    cx_engine = object()
    ae_app = object()
    ae_marker_id = "marker-0274"

    def __init__(self) -> None:
        self.cleanup_session_id: str | None = None
        self.cx_upload_client = type(
            "FakeCxUploadClient",
            (),
            {"calls": [{"status_code": 202, "dedupe_status": "CREATED"}]},
        )()
        self.cx_owner_resolver = type(
            "FakeCxOwnerResolver",
            (),
            {"calls": [{"ensure": False}]},
        )()

    def cleanup(self, *, session_id: str | None) -> dict[str, Any]:
        self.cleanup_session_id = session_id
        return {
            "ae_marker_rows_after_delete": 0,
            "oa_rows": {"deleted_sessions": 1},
            "cx_rows": {
                "deleted_acl_entries": 1,
                "deleted_content_objects": 1,
                "deleted_source_files": 1,
            },
        }


def enabled_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        smoke.TENANT_ID_ENV: "tenant-upload-0274",
        smoke.SUBJECT_ID_ENV: "user-upload-0274",
        smoke.EMPLOYEE_ID_ENV: "EMP-UPLOAD-0274",
        smoke.PASSWORD_ENV: "playwright-upload-secret-0274",
        smoke.SOURCE_SHA256_ENV: FakePrepared.source_sha256,
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret@127.0.0.1:5432/nex_oa_test"
        ),
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:secret@127.0.0.1:5432/nex_cx_test"
        ),
    }


def readiness_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "readiness_schema_version": "ae_web_playwright_readiness.v1",
        "status": "PASS",
    }


def boundary_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "boundary_schema_version": "ae_web_same_origin_runtime_boundary.v1",
        "status": "PASS",
    }


def node_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "smoke_schema_version": smoke.NODE_SMOKE_SCHEMA_VERSION,
        "status": "PASS",
        "browser_observations": {
            "route_guard_status_after_login": "allowed",
            "upload_feedback_status": "accepted",
            "route_guard_status_after_logout": "blocked",
        },
        "request_observations": {
            "ae_api_request_count": 4,
            "ae_api_response_count": 4,
            "upload_response_status": 202,
            "request_routes": [
                {"method": "GET", "route": "/ae-api/api/v1/auth/session"},
                {"method": "POST", "route": "/ae-api/api/v1/auth/session/login"},
                {
                    "method": "POST",
                    "route": "/ae-api/api/v1/uploads/files",
                    "body_summary": {
                        "body_kind": "multipart",
                        "multipart_content_type_present": True,
                        "field_introspection_status": "available",
                        "file_field_present": True,
                        "source_sha256_field_present": True,
                        "tenant_id_field_present": True,
                        "owner_user_id_field_present": True,
                        "uploaded_by_user_id_field_present": True,
                        "raw_source_serialized_in_evidence": False,
                    },
                },
                {"method": "POST", "route": "/ae-api/api/v1/auth/session/logout"},
            ],
            "response_routes": [
                {"status": 401, "route": "/ae-api/api/v1/auth/session"},
                {"status": 200, "route": "/ae-api/api/v1/auth/session/login"},
                {"status": 202, "route": "/ae-api/api/v1/uploads/files"},
                {"status": 200, "route": "/ae-api/api/v1/auth/session/logout"},
            ],
        },
        "checks": {
            "playwright_browser_launched": True,
            "same_origin_login_called": True,
            "same_origin_upload_called": True,
            "same_origin_logout_called": True,
            "upload_response_accepted": True,
            "upload_feedback_accepted": True,
            "upload_body_multipart": True,
            "upload_multipart_content_type_present": True,
            "upload_multipart_body_shape_safe": True,
            "upload_multipart_fields_present_when_introspected": True,
            "upload_body_not_serialized_in_evidence": True,
        },
    }


def session_observations(_engine: object, **_kwargs: object) -> dict[str, Any]:
    return {
        "session_id": "session-0274",
        "membership_count": 1,
        "credential_count": 1,
        "session_count": 1,
        "session_status": "REVOKED",
        "session_revoked_at_present": True,
        "session_subject_matches": True,
    }


def cx_observations(_engine: object, **_kwargs: object) -> dict[str, Any]:
    return {
        "document_id": "doc-0274",
        "source_file_id": "source-0274",
        "content_object_count": 1,
        "source_file_count": 1,
        "owner_refs_match": True,
        "source_sha256_present": True,
        "checksum_verified_at_present": True,
        "storage_backend": "local_filesystem",
        "lifecycle_status": "ACTIVE",
    }


def started(url: str) -> smoke.login_pg.StartedServer:
    return smoke.login_pg.StartedServer(url=url, stop=lambda: None)


def test_upload_playwright_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_web_authenticated_upload_playwright_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        "ae_web_authenticated_upload_playwright_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_upload_playwright_postgres_smoke_passes_with_injected_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = FakePrepared()
    monkeypatch.setattr(smoke.base_auth, "_count_ae_marker_rows", lambda *_args, **_kwargs: 1)

    evidence = smoke.run_ae_web_authenticated_upload_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=readiness_pass,
        boundary_runner=boundary_pass,
        prepare_runner=lambda _env, _profile: prepared,
        node_runner=node_pass,
        session_observer=session_observations,
        cx_observer=cx_observations,
        port_allocator=iter([18004, 15228]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["checks"]["cx_content_object_persisted"] is True
    assert evidence["checks"]["cx_source_checksum_verified"] is True
    assert evidence["db_observations"]["cx"]["content_object_count"] == 1
    assert evidence["upload_observations"]["browser_source_bytes_sent"] is True
    assert evidence["cleanup_observations"]["cx_rows"]["deleted_source_files"] == 1
    assert prepared.cleanup_session_id == "session-0274"
    assert enabled_env()[smoke.PASSWORD_ENV] not in serialized
    assert FakePrepared.source_sha256 not in serialized
    assert "secret@127.0.0.1" not in serialized
    assert smoke.summary_line(evidence) == (
        "ae_web_authenticated_upload_playwright_postgres_smoke=pass "
        "profile=test upload=accepted cx_content=1 cx_checksum=verified "
        "oa_session_status=REVOKED "
        "live_db=true browser=playwright"
    )


def test_upload_playwright_postgres_smoke_reports_failure_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = enabled_env()
    monkeypatch.setattr(smoke.base_auth, "_count_ae_marker_rows", lambda *_args, **_kwargs: 1)

    non_test = dict(env, **{smoke.PROFILE_ENV: "dev"})
    readiness_failed = smoke.run_ae_web_authenticated_upload_playwright_postgres_smoke(
        env,
        readiness_runner=lambda _env: {"status": "FAIL", "readiness_schema_version": "x"},
    )
    boundary_failed = smoke.run_ae_web_authenticated_upload_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        boundary_runner=lambda _env: {"status": "FAIL", "boundary_schema_version": "x"},
        prepare_runner=lambda _env, _profile: FakePrepared(),
        node_runner=node_pass,
        session_observer=session_observations,
        cx_observer=cx_observations,
        port_allocator=iter([18004, 15228]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )
    node_failed = smoke.run_ae_web_authenticated_upload_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        boundary_runner=boundary_pass,
        prepare_runner=lambda _env, _profile: FakePrepared(),
        node_runner=lambda _env: {**node_pass(_env), "status": "FAIL"},
        session_observer=session_observations,
        cx_observer=cx_observations,
        port_allocator=iter([18004, 15228]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )
    config_failed = smoke.run_ae_web_authenticated_upload_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(ValueError("bad")),
    )
    execution_failed = smoke.run_ae_web_authenticated_upload_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert smoke.run_ae_web_authenticated_upload_playwright_postgres_smoke(non_test)["failure_code"] == "profile_not_allowed"
    assert readiness_failed["failure_code"] == "readiness_failed"
    assert boundary_failed["failure_code"] == "same_origin_boundary_failed"
    assert node_failed["status"] == "FAIL"
    assert any(issue["subject"] == "node_playwright_smoke_passed" for issue in node_failed["issues"])
    assert config_failed["failure_code"] == "configuration_invalid"
    assert execution_failed["failure_code"] == "execution_failed"


def test_node_playwright_upload_runner_parses_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def completed(returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["node"], returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, json.dumps(node_pass({}))),
    )
    assert smoke.run_node_playwright_upload_smoke({})["status"] == "PASS"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(1, ""),
    )
    assert smoke.run_node_playwright_upload_smoke({})["failure_code"] == "node_playwright_failed"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, "not-json"),
    )
    assert smoke.run_node_playwright_upload_smoke({})["failure_code"] == "node_json_invalid"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, "[]"),
    )
    assert smoke.run_node_playwright_upload_smoke({})["failure_code"] == "node_payload_invalid"


def test_latest_cx_upload_observations_and_cleanup_use_real_sql(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'cx-smoke.db'}"
    engine = smoke.base_auth.build_engine(database_url)
    source_sha256 = FakePrepared.source_sha256
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_source_files (
                    source_file_id TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL,
                    storage_backend TEXT NOT NULL,
                    checksum_verified_at TEXT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_objects (
                    content_object_id TEXT PRIMARY KEY,
                    source_file_id TEXT NOT NULL,
                    lifecycle_status TEXT NOT NULL,
                    tenant_ref_type TEXT NOT NULL,
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_type TEXT NOT NULL,
                    owner_subject_ref_id TEXT NOT NULL,
                    uploaded_by_subject_ref_type TEXT NOT NULL,
                    uploaded_by_subject_ref_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_acl_entries (
                    acl_entry_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_source_files (
                    source_file_id, source_sha256, storage_backend, checksum_verified_at
                )
                VALUES ('source-0274', :source_sha256, 'local_filesystem', NULL)
                """
            ),
            {"source_sha256": source_sha256},
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_content_objects (
                    content_object_id,
                    source_file_id,
                    lifecycle_status,
                    tenant_ref_type,
                    tenant_ref_id,
                    owner_subject_ref_type,
                    owner_subject_ref_id,
                    uploaded_by_subject_ref_type,
                    uploaded_by_subject_ref_id,
                    source_sha256,
                    created_at
                )
                VALUES (
                    'doc-0274',
                    'source-0274',
                    'ACTIVE',
                    'oa.tenant',
                    'tenant-upload-0274',
                    'oa.user',
                    'user-upload-0274',
                    'oa.user',
                    'user-upload-0274',
                    :source_sha256,
                    '2026-08-13T00:00:00Z'
                )
                """
            ),
            {"source_sha256": source_sha256},
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_content_acl_entries (acl_entry_id, content_object_id)
                VALUES ('acl-0274', 'doc-0274')
                """
            )
        )

    observations = smoke.latest_cx_upload_observations(
        engine,
        tenant_id="tenant-upload-0274",
        owner_user_id="user-upload-0274",
        source_sha256=source_sha256,
    )
    cleanup = smoke._delete_cx_smoke_rows(
        engine,
        tenant_id="tenant-upload-0274",
        owner_user_id="user-upload-0274",
        source_sha256=source_sha256,
    )
    empty = smoke.latest_cx_upload_observations(
        engine,
        tenant_id="tenant-upload-0274",
        owner_user_id="user-upload-0274",
        source_sha256=source_sha256,
    )

    assert observations["content_object_count"] == 1
    assert observations["source_file_count"] == 1
    assert observations["owner_refs_match"] is True
    assert observations["checksum_verified_at_present"] is False
    assert cleanup == {
        "deleted_acl_entries": 1,
        "deleted_content_objects": 1,
        "deleted_source_files": 1,
    }
    assert empty["document_id"] is None
    assert empty["content_object_count"] == 0


def test_cx_upload_client_owner_resolver_and_prepared_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 202

        def json(self) -> dict[str, Any]:
            return {
                "document_id": "doc-0274",
                "dedupe": {"status": "CREATED"},
            }

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self) -> None:
            self.posts: list[dict[str, Any]] = []

        def post(self, path: str, *, headers: dict[str, str], json: dict[str, Any]):
            self.posts.append({"path": path, "headers": headers, "json": json})
            return Response()

    class TempDir:
        def __init__(self) -> None:
            self.cleaned = False

        def cleanup(self) -> None:
            self.cleaned = True

    monkeypatch.setattr(
        smoke,
        "_cx_service_headers",
        lambda *, trace_id, request_id: {
            "Authorization": "Bearer redacted",
            "X-Request-ID": request_id,
            "traceparent": trace_id,
        },
    )
    client = Client()
    adapter = smoke.TestClientCxUploadClient(client)
    payload = adapter.register_upload(
        {"filename": "metadata.md"},
        request_id="request-0274",
        trace_id="trace0274",
    )
    resolver = smoke.StaticOwnerResolver()
    ownership_ref = {
        "tenant_ref": {"type": "oa.tenant", "id": "tenant"},
        "owner_subject_ref": {"type": "oa.user", "id": "user"},
        "uploaded_by_subject_ref": {"type": "oa.user", "id": "user"},
    }
    resolved = resolver.resolve_ownership_ref(
        ownership_ref,
        request_id="request-0274",
        trace_id="trace0274",
    )
    temp_dir = TempDir()
    prepared = smoke.PreparedAuthenticatedUploadPlaywrightPostgresSmoke(
        profile="test",
        request_id="request-0274",
        trace_id="trace0274",
        tenant_id="tenant",
        subject_id="subject",
        employee_id="EMP0274",
        password="dummy-password",
        filename="metadata.md",
        content_type="text/markdown",
        size_bytes=12,
        source_sha256=FakePrepared.source_sha256,
        database_envs={},
        redacted_database_urls={},
        migrations={},
        ae_engine="ae-engine",
        oa_engine="oa-engine",
        cx_engine="cx-engine",
        ae_app=object(),
        ae_marker_id="marker",
        cx_upload_client=adapter,
        cx_owner_resolver=resolver,
        storage_tempdir=temp_dir,
    )
    marker_calls: list[dict[str, object]] = []
    oa_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        smoke.base_auth,
        "_delete_ae_smoke_marker",
        lambda engine, *, event_id: marker_calls.append(
            {"engine": engine, "event_id": event_id}
        )
        or 0,
    )
    monkeypatch.setattr(
        smoke.base_auth,
        "_delete_oa_smoke_rows",
        lambda engine, **kwargs: oa_calls.append({"engine": engine, **kwargs})
        or {"deleted_sessions": 1},
    )
    monkeypatch.setattr(
        smoke,
        "_delete_cx_smoke_rows",
        lambda engine, **kwargs: {"deleted_content_objects": 1, "engine": engine},
    )

    cleanup = prepared.cleanup(session_id="session-0274")

    assert payload["document_id"] == "doc-0274"
    assert adapter.calls == [
        {
            "operation": "register_upload",
            "status_code": 202,
            "dedupe_status": "CREATED",
        }
    ]
    assert client.posts[0]["path"] == "/api/v1/documents/uploads"
    assert resolved["resolution_status"] == "RESOLVED"
    assert resolver.calls[0]["ensure"] is False
    assert marker_calls == [{"engine": "ae-engine", "event_id": "marker"}]
    assert oa_calls[0]["session_id"] == "session-0274"
    assert cleanup["cx_rows"]["deleted_content_objects"] == 1
    assert temp_dir.cleaned is True


def test_delete_cx_smoke_rows_keeps_shared_source_file(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'cx-shared-source.db'}"
    engine = smoke.base_auth.build_engine(database_url)
    source_sha256 = FakePrepared.source_sha256
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_source_files (
                    source_file_id TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_objects (
                    content_object_id TEXT PRIMARY KEY,
                    source_file_id TEXT NOT NULL,
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_acl_entries (
                    acl_entry_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_source_files (source_file_id, source_sha256)
                VALUES ('source-0274', :source_sha256)
                """
            ),
            {"source_sha256": source_sha256},
        )
        for document_id, tenant_id, owner_id in [
            ("doc-0274", "tenant-upload-0274", "user-upload-0274"),
            ("doc-shared", "tenant-other", "user-other"),
        ]:
            connection.execute(
                text(
                    """
                    INSERT INTO cx_content_objects (
                        content_object_id,
                        source_file_id,
                        tenant_ref_id,
                        owner_subject_ref_id,
                        source_sha256
                    )
                    VALUES (
                        :document_id,
                        'source-0274',
                        :tenant_id,
                        :owner_id,
                        :source_sha256
                    )
                    """
                ),
                {
                    "document_id": document_id,
                    "tenant_id": tenant_id,
                    "owner_id": owner_id,
                    "source_sha256": source_sha256,
                },
            )

    cleanup = smoke._delete_cx_smoke_rows(
        engine,
        tenant_id="tenant-upload-0274",
        owner_user_id="user-upload-0274",
        source_sha256=source_sha256,
    )
    with engine.connect() as connection:
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()

    assert cleanup["deleted_content_objects"] == 1
    assert cleanup["deleted_source_files"] == 0
    assert remaining_sources == 1
    assert remaining_content == 1


def test_helpers_redaction_node_env_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "evidence.json"
    evidence = {"status": "PASS", "profile": "test"}

    smoke.write_smoke_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    with pytest.raises(ValueError, match=smoke.PASSWORD_ENV):
        smoke.assert_smoke_evidence_redacted(
            "playwright-upload-secret-0274",
            {smoke.PASSWORD_ENV: "playwright-upload-secret-0274"},
        )
    with pytest.raises(ValueError, match=smoke.SOURCE_SHA256_ENV):
        smoke.assert_smoke_evidence_redacted(
            FakePrepared.source_sha256,
            {smoke.SOURCE_SHA256_ENV: FakePrepared.source_sha256},
        )

    node_env = smoke._node_environ(
        {
            smoke.CHROMIUM_EXECUTABLE_ENV: "/usr/bin/google-chrome",
            smoke.TIMEOUT_MS_ENV: "20000",
        },
        web_url="http://127.0.0.1:5228/",
        tenant_id="tenant",
        employee_id="EMP0274",
        password="dummy-password",
        filename="x.md",
        content_type="text/markdown",
        size_bytes=12,
        source_sha256=FakePrepared.source_sha256,
    )
    assert node_env[smoke.CHROMIUM_EXECUTABLE_ENV] == "/usr/bin/google-chrome"
    assert node_env[smoke.TIMEOUT_MS_ENV] == "20000"
    assert node_env[smoke.SIZE_BYTES_ENV] == "12"
    assert smoke._bounded_size_bytes(None) == smoke.DEFAULT_SIZE_BYTES
    assert smoke._bounded_size_bytes("2097152") == 2097152
    with pytest.raises(ValueError, match=smoke.SIZE_BYTES_ENV):
        smoke._bounded_size_bytes("bad")
    with pytest.raises(ValueError, match=smoke.SIZE_BYTES_ENV):
        smoke._bounded_size_bytes("-1")
    deterministic_sha256 = smoke._deterministic_upload_source_sha256(12)
    assert (
        smoke._source_sha256_for_upload_bytes(12, explicit_value=None)
        == deterministic_sha256
    )
    assert (
        smoke._source_sha256_for_upload_bytes(
            12,
            explicit_value=deterministic_sha256.upper(),
        )
        == deterministic_sha256
    )
    with pytest.raises(ValueError, match="deterministic smoke file bytes"):
        smoke._source_sha256_for_upload_bytes(
            12,
            explicit_value=FakePrepared.source_sha256,
        )
    assert smoke._valid_sha256(FakePrepared.source_sha256.upper()) == FakePrepared.source_sha256
    with pytest.raises(ValueError, match=smoke.SOURCE_SHA256_ENV):
        smoke._valid_sha256("not-a-hash")
    storage = smoke._storage_config(tmp_path)
    headers = smoke._cx_service_headers(trace_id="0" * 32, request_id="request-0274")
    assert storage.chunk_policy == "chunk_1000_100"
    assert headers["X-Service-ID"] == smoke.base_auth.AE_SERVICE_ID
    assert smoke._source_status(None, version_key="x") == {"status": "NOT_RUN"}
    assert smoke._source_status({"status": "PASS", "x": "v1"}, version_key="x") == {
        "status": "PASS",
        "schema_version": "v1",
    }
    assert smoke._source_status({"status": "PASS"}, version_key="missing") == {
        "status": "PASS"
    }
    assert smoke._safe_response_json(object()) == {}
    assert smoke._safe_response_json(type("Response", (), {"json": lambda self: []})()) == {}

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_authenticated_upload_playwright_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "not enabled"},
    )
    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_authenticated_upload_playwright_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "x"},
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=x" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_authenticated_upload_playwright_postgres_smoke",
        lambda: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main([]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_quality_gate_docs_and_package_wiring() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    package = json.loads(
        (root / "apps" / "nex-ae-web" / "package.json").read_text(encoding="utf-8")
    )
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0274_ae_web_authenticated_upload_playwright_postgresql_smoke.md"
    )

    assert (
        "run_ae_web_authenticated_upload_playwright_postgres_smoke.py --summary"
        in quality_gate
    )
    assert "0274_ae_web_authenticated_upload_playwright_postgresql_smoke.md" in docs_index
    assert package["scripts"]["smoke:authenticated-upload-playwright"]
    assert slice_doc.exists()
