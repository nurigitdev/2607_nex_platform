from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import run_ae_web_credential_login_playwright_postgres_smoke as smoke


class FakePrepared:
    profile = "test"
    request_id = "request-0270"
    trace_id = "trace0270"
    tenant_id = "tenant-playwright-0270"
    subject_id = "user-playwright-0270"
    employee_id = "EMP-PLAYWRIGHT-0270"
    password = "playwright-secret-0270"
    ae_database_env = "NEX_AE_TEST_DATABASE_URL"
    oa_database_env = "NEX_OA_TEST_DATABASE_URL"
    redacted_database_urls = {
        "ae": "postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test",
        "oa": "postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test",
    }
    migrations = {
        "ae": {"service_id": "nex-ae-api", "profile": "test"},
        "oa": {"service_id": "nex-oa", "profile": "test"},
    }
    ae_engine = object()
    oa_engine = object()
    ae_app = object()
    ae_marker_id = "marker-0270"

    def __init__(self) -> None:
        self.cleanup_session_id: str | None = None

    def cleanup(self, *, session_id: str | None) -> dict[str, Any]:
        self.cleanup_session_id = session_id
        return {
            "ae_marker_rows_after_delete": 0,
            "oa_rows": {
                "deleted_sessions": 1,
                "deleted_credentials": 1,
                "deleted_memberships": 1,
                "deleted_subjects": 1,
                "deleted_tenants": 1,
            },
        }


def enabled_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        smoke.TENANT_ID_ENV: "tenant-playwright-0270",
        smoke.SUBJECT_ID_ENV: "user-playwright-0270",
        smoke.EMPLOYEE_ID_ENV: "EMP-PLAYWRIGHT-0270",
        smoke.PASSWORD_ENV: "playwright-secret-0270",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret@127.0.0.1:5432/nex_oa_test"
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
        "proxy": {"prefix": "/ae-api"},
    }


def node_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "smoke_schema_version": smoke.NODE_SMOKE_SCHEMA_VERSION,
        "status": "PASS",
        "browser_observations": {
            "route_guard_status_after_login": "allowed",
            "route_guard_status_after_logout": "blocked",
        },
        "request_observations": {
            "ae_api_request_count": 3,
            "request_routes": [
                {"method": "GET", "route": "/ae-api/api/v1/auth/session"},
                {"method": "POST", "route": "/ae-api/api/v1/auth/session/login"},
                {"method": "POST", "route": "/ae-api/api/v1/auth/session/logout"},
            ],
        },
        "checks": {
            "playwright_browser_launched": True,
            "same_origin_login_called": True,
            "same_origin_logout_called": True,
            "route_guard_allowed_after_login": True,
            "logout_feedback_logged_out": True,
        },
    }


def session_observations(_engine: object, **_kwargs: object) -> dict[str, Any]:
    return {
        "session_id": "session-0270",
        "membership_count": 1,
        "credential_count": 1,
        "session_count": 1,
        "session_status": "REVOKED",
        "session_revoked_at_present": True,
        "session_subject_matches": True,
    }


def started(url: str) -> smoke.StartedServer:
    return smoke.StartedServer(url=url, stop=lambda: None)


def test_playwright_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_web_credential_login_playwright_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_playwright_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_playwright_postgres_smoke_passes_with_injected_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = FakePrepared()
    monkeypatch.setattr(smoke.base_auth, "_count_ae_marker_rows", lambda *_args, **_kwargs: 1)

    evidence = smoke.run_ae_web_credential_login_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=readiness_pass,
        boundary_runner=boundary_pass,
        prepare_runner=lambda _env, _profile: prepared,
        node_runner=node_pass,
        session_observer=session_observations,
        port_allocator=iter([18003, 15227]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["checks"]["node_playwright_smoke_passed"] is True
    assert evidence["checks"]["oa_session_revoked"] is True
    assert evidence["db_observations"]["oa_session_status"] == "REVOKED"
    assert evidence["cleanup_observations"]["ae_marker_rows_after_delete"] == 0
    assert prepared.cleanup_session_id == "session-0270"
    assert enabled_env()[smoke.PASSWORD_ENV] not in serialized
    assert "secret@127.0.0.1" not in serialized
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_playwright_postgres_smoke=pass "
        "profile=test route_guard=allowed oa_session_status=REVOKED "
        "live_db=true browser=playwright"
    )


def test_playwright_postgres_smoke_reports_failure_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = enabled_env()
    monkeypatch.setattr(smoke.base_auth, "_count_ae_marker_rows", lambda *_args, **_kwargs: 1)

    non_test = dict(env, **{smoke.PROFILE_ENV: "dev"})
    readiness_failed = smoke.run_ae_web_credential_login_playwright_postgres_smoke(
        env,
        readiness_runner=lambda _env: {"status": "FAIL", "readiness_schema_version": "x"},
    )
    boundary_failed = smoke.run_ae_web_credential_login_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        boundary_runner=lambda _env: {"status": "FAIL", "boundary_schema_version": "x"},
        prepare_runner=lambda _env, _profile: FakePrepared(),
        node_runner=node_pass,
        session_observer=session_observations,
        port_allocator=iter([18003, 15227]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )
    node_failed = smoke.run_ae_web_credential_login_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        boundary_runner=boundary_pass,
        prepare_runner=lambda _env, _profile: FakePrepared(),
        node_runner=lambda _env: {**node_pass(_env), "status": "FAIL"},
        session_observer=session_observations,
        port_allocator=iter([18003, 15227]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )
    config_failed = smoke.run_ae_web_credential_login_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(ValueError("bad")),
    )
    execution_failed = smoke.run_ae_web_credential_login_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert smoke.run_ae_web_credential_login_playwright_postgres_smoke(non_test)["failure_code"] == "profile_not_allowed"
    assert readiness_failed["failure_code"] == "readiness_failed"
    assert boundary_failed["failure_code"] == "same_origin_boundary_failed"
    assert node_failed["status"] == "FAIL"
    assert any(issue["subject"] == "node_playwright_smoke_passed" for issue in node_failed["issues"])
    assert config_failed["failure_code"] == "configuration_invalid"
    assert execution_failed["failure_code"] == "execution_failed"


def test_node_playwright_smoke_runner_parses_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def completed(returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["node"], returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, json.dumps(node_pass({}))),
    )
    assert smoke.run_node_playwright_smoke({})["status"] == "PASS"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(1, ""),
    )
    assert smoke.run_node_playwright_smoke({})["failure_code"] == "node_playwright_failed"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, "not-json"),
    )
    assert smoke.run_node_playwright_smoke({})["failure_code"] == "node_json_invalid"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, "[]"),
    )
    assert smoke.run_node_playwright_smoke({})["failure_code"] == "node_payload_invalid"


def test_latest_session_observations_handles_empty_and_present_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        def __init__(self, row: dict[str, Any] | None = None, scalar: int = 0) -> None:
            self.row = row
            self.scalar = scalar

        def scalar_one(self) -> int:
            return self.scalar

        def mappings(self) -> "Result":
            return self

        def first(self) -> dict[str, Any] | None:
            return self.row

    class Connection:
        def __init__(self, row: dict[str, Any] | None) -> None:
            self.row = row
            self.calls = 0

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, *_args: object, **_kwargs: object) -> Result:
            self.calls += 1
            if self.calls == 1:
                return Result(scalar=1 if self.row else 0)
            if self.calls == 2:
                return Result(scalar=1 if self.row else 0)
            return Result(self.row)

    class Engine:
        def __init__(self, row: dict[str, Any] | None) -> None:
            self.row = row

        def connect(self) -> Connection:
            return Connection(self.row)

    empty = smoke.latest_session_observations(
        Engine(None),
        tenant_id="tenant",
        subject_id="subject",
    )
    monkeypatch.setattr(
        smoke.base_auth,
        "_db_observations",
        lambda *_args, **_kwargs: {
            "membership_count": 1,
            "credential_count": 1,
            "session_count": 1,
            "session_status": "REVOKED",
            "session_revoked_at": "2026-08-13T00:00:00Z",
            "session_tenant_id": "tenant",
            "session_subject_id": "subject",
        },
    )
    present = smoke.latest_session_observations(
        Engine({"session_id": "session-0270"}),
        tenant_id="tenant",
        subject_id="subject",
    )

    assert empty["session_count"] == 0
    assert present["session_status"] == "REVOKED"
    assert present["session_subject_matches"] is True


def test_redaction_output_helpers_and_main(
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
            "playwright-secret-0270",
            {smoke.PASSWORD_ENV: "playwright-secret-0270"},
        )

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_playwright_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "not enabled"},
    )
    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_playwright_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "x"},
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=x" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_playwright_postgres_smoke",
        lambda: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main([]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_prepared_cleanup_node_env_and_source_status_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    prepared = smoke.PreparedPlaywrightPostgresSmoke(
        profile="test",
        request_id="request-0270",
        trace_id="trace0270",
        tenant_id="tenant",
        subject_id="subject",
        employee_id="EMP0270",
        password="dummy-password",
        ae_database_env="NEX_AE_TEST_DATABASE_URL",
        oa_database_env="NEX_OA_TEST_DATABASE_URL",
        redacted_database_urls={},
        migrations={},
        ae_engine="ae-engine",
        oa_engine="oa-engine",
        ae_app=object(),
        ae_marker_id="marker",
    )

    cleanup = prepared.cleanup(session_id="session")
    node_env = smoke._node_environ(
        {
            smoke.CHROMIUM_EXECUTABLE_ENV: "/usr/bin/google-chrome",
            smoke.TIMEOUT_MS_ENV: "15000",
        },
        web_url="http://127.0.0.1:5227/",
        tenant_id="tenant",
        employee_id="EMP0270",
        password="dummy-password",
    )

    assert cleanup["ae_marker_rows_after_delete"] == 0
    assert cleanup["oa_rows"]["deleted_sessions"] == 1
    assert marker_calls == [{"engine": "ae-engine", "event_id": "marker"}]
    assert oa_calls[0]["session_id"] == "session"
    assert node_env[smoke.CHROMIUM_EXECUTABLE_ENV] == "/usr/bin/google-chrome"
    assert node_env[smoke.TIMEOUT_MS_ENV] == "15000"
    assert smoke._source_status({"status": "PASS"}, version_key="missing") == {
        "status": "PASS"
    }


def test_playwright_postgres_smoke_is_quality_gate_docs_and_package_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    ae_web_readme = (root / "apps" / "nex-ae-web" / "README.md").read_text(
        encoding="utf-8"
    )
    package = json.loads((root / "apps" / "nex-ae-web" / "package.json").read_text(
        encoding="utf-8"
    ))
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0270_ae_web_credential_login_playwright_postgresql_smoke.md"
    )

    assert "run_ae_web_credential_login_playwright_postgres_smoke.py --summary" in quality_gate
    assert "0270_ae_web_credential_login_playwright_postgresql_smoke.md" in docs_index
    assert "Slice 0270" in ae_web_readme
    assert package["scripts"]["smoke:credential-login-playwright"]
    assert slice_doc.exists()
