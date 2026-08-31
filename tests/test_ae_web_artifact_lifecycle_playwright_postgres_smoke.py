from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

import run_ae_web_artifact_lifecycle_playwright_postgres_smoke as smoke


class FakePrepared:
    profile = "test"
    request_id = "request-0458"
    trace_id = "trace0458"
    database_env = "NEX_AE_TEST_DATABASE_URL"
    redacted_database_url = (
        "postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test"
    )
    migration = {"service_id": "nex-ae-api", "profile": "test"}
    ae_app = object()
    tenant_id = "tenant-lifecycle-0458"
    workspace_id = "workspace-lifecycle-0458"
    owner_user_id = "owner-lifecycle-0458"
    artifact_handoff_id = "handoff-lifecycle-0458"
    artifact_id = "artifact-lifecycle-0458"
    materialized_file_count = 2

    def __init__(self) -> None:
        self.cleaned = False
        self.disposed = False
        self.storage_tempdir = tempfile.TemporaryDirectory(
            prefix="nex-test-artifact-lifecycle-playwright-"
        )
        self.engine = type(
            "FakeEngine",
            (),
            {"dispose": lambda inner_self: setattr(self, "disposed", True)},
        )()

    def cleanup(self) -> dict[str, int]:
        self.cleaned = True
        self.storage_tempdir.cleanup()
        return {"artifacts": 1, "handoffs": 1}


def enabled_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0458@127.0.0.1:5432/nex_ae_test"
        ),
    }


def readiness_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "readiness_schema_version": "ae_web_playwright_readiness.v1",
        "status": "PASS",
    }


def lifecycle_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "smoke_schema_version": "ae_artifact_lifecycle_postgres_smoke.v1",
        "status": "PASS",
        "lifecycle": {
            "archive_status": "ARCHIVED",
            "restore_status": "READY",
            "delete_status": "DELETED",
        },
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
            "artifact_lifecycle_shell_dom_present": True,
            "artifact_status_before": "READY",
            "archive_status": "ARCHIVED",
            "restore_status": "READY",
            "delete_status": "DELETED",
            "final_status": "DELETED",
            "lifecycle_post_count": 3,
        },
        "lifecycle": {
            "before_summary": {"artifact_id": "artifact-lifecycle-0458", "status": "READY"},
            "archive": {
                "artifact_status": "ARCHIVED",
                "transition_applied": True,
                "comment_hash_present": True,
                "comment_length": 23,
            },
            "restore": {
                "artifact_status": "READY",
                "restore_status": "READY",
                "transition_applied": True,
            },
            "mark_deleted": {
                "artifact_status": "DELETED",
                "transition_applied": True,
            },
            "final_summary": {"artifact_id": "artifact-lifecycle-0458", "status": "DELETED"},
        },
        "request_observations": {
            "ae_api_request_count": 7,
            "ae_api_response_count": 7,
            "request_routes": [
                {
                    "method": "GET",
                    "route": "/ae-api/api/v1/artifacts/artifact-lifecycle-0458",
                },
                {
                    "method": "POST",
                    "route": "/ae-api/api/v1/artifacts/artifact-lifecycle-0458/lifecycle-actions",
                },
            ],
            "response_routes": [],
        },
        "checks": {
            "playwright_browser_launched": True,
            "artifact_lifecycle_shell_dom_present": True,
            "artifact_detail_called": True,
            "artifact_lifecycle_post_called": True,
            "browser_request_secret_header_absent": True,
            "archive_transition_applied": True,
            "restore_transition_applied": True,
            "delete_transition_applied": True,
            "final_artifact_deleted": True,
            "deleted_restore_available": True,
            "lifecycle_metadata_only": True,
        },
    }


def artifact_observations(_engine: object, **_kwargs: object) -> dict[str, Any]:
    return {
        "ready_rows": 0,
        "archived_rows": 0,
        "deleted_rows": 1,
        "file_rows": 2,
        "link_rows": 4,
    }


def started(url: str) -> smoke.login_pg.StartedServer:
    return smoke.login_pg.StartedServer(url=url, stop=lambda: None)


def run_with_injected_runtime(
    *,
    prepared: FakePrepared | None = None,
    node_runner=node_pass,
    readiness_runner=readiness_pass,
    lifecycle_runner=lifecycle_pass,
    boundary_runner=boundary_pass,
    artifact_observer=artifact_observations,
) -> dict[str, Any]:
    prepared = prepared or FakePrepared()
    return smoke.run_ae_web_artifact_lifecycle_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=readiness_runner,
        lifecycle_runner=lifecycle_runner,
        boundary_runner=boundary_runner,
        prepare_runner=lambda _env, _profile: prepared,
        node_runner=node_runner,
        artifact_observer=artifact_observer,
        port_allocator=iter([18058, 15258]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )


def test_artifact_lifecycle_playwright_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_web_artifact_lifecycle_playwright_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        "ae_web_artifact_lifecycle_playwright_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_artifact_lifecycle_playwright_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_web_artifact_lifecycle_playwright_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_web_artifact_lifecycle_playwright_postgres_smoke=fail "
        "reason=profile_not_allowed"
    )


def test_artifact_lifecycle_playwright_postgres_smoke_passes_with_injected_runtime() -> None:
    prepared = FakePrepared()
    evidence = run_with_injected_runtime(prepared=prepared)
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["checks"]["artifact_lifecycle_postgres_passed"] is True
    assert evidence["checks"]["browser_archive_restore_delete_applied"] is True
    assert evidence["checks"]["ae_test_database_connected"] is True
    assert evidence["db_observations"]["deleted_rows"] == 1
    assert evidence["cleanup_observations"] == {"artifacts": 1, "handoffs": 1}
    assert prepared.cleaned is True
    assert prepared.disposed is True
    assert "secret-0458" not in serialized
    assert "Move out of active view" not in serialized
    assert smoke.summary_line(evidence) == (
        "ae_web_artifact_lifecycle_playwright_postgres_smoke=pass "
        "profile=test artifact=artifact-lifecycle-0458 archive=ARCHIVED "
        "restore=READY delete=DELETED deleted_rows=1 "
        "live_db=true browser=playwright"
    )


def test_artifact_lifecycle_playwright_postgres_smoke_reports_failures() -> None:
    readiness_failed = smoke.run_ae_web_artifact_lifecycle_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=lambda _env: {"status": "FAIL", "readiness_schema_version": "x"},
    )
    lifecycle_failed = smoke.run_ae_web_artifact_lifecycle_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=readiness_pass,
        lifecycle_runner=lambda _env: {
            "smoke_schema_version": "x",
            "status": "FAIL",
            "failure_code": "configuration_invalid",
        },
    )
    boundary_failed = run_with_injected_runtime(
        boundary_runner=lambda _env: {"status": "FAIL", "boundary_schema_version": "x"}
    )
    node_failed = run_with_injected_runtime(
        node_runner=lambda _env: {**node_pass(_env), "status": "FAIL"}
    )
    db_check_failed = run_with_injected_runtime(
        artifact_observer=lambda _engine, **_kwargs: {
            **artifact_observations(_engine),
            "ready_rows": 1,
            "deleted_rows": 0,
        }
    )
    config_failed = smoke.run_ae_web_artifact_lifecycle_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=readiness_pass,
        lifecycle_runner=lifecycle_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(
            ValueError("bad config")
        ),
    )
    execution_failed = smoke.run_ae_web_artifact_lifecycle_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=readiness_pass,
        lifecycle_runner=lifecycle_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(
            RuntimeError("transient browser launch failure")
        ),
    )

    assert readiness_failed["failure_code"] == "readiness_failed"
    assert lifecycle_failed["failure_code"] == "artifact_lifecycle_postgres_failed"
    assert boundary_failed["failure_code"] == "same_origin_boundary_failed"
    assert node_failed["status"] == "FAIL"
    assert node_failed["issues"] == [
        {"category": "check_failed", "subject": "node_playwright_smoke_passed"}
    ]
    assert db_check_failed["status"] == "FAIL"
    assert {"category": "check_failed", "subject": "ae_test_database_connected"} in (
        db_check_failed["issues"]
    )
    assert config_failed["failure_code"] == "configuration_invalid"
    assert execution_failed["failure_code"] == "execution_failed"


def test_artifact_lifecycle_playwright_node_runner_parses_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            stdout='{"status":"PASS","smoke_schema_version":"x"}',
            stderr="",
        ),
    )
    assert smoke.run_node_artifact_lifecycle_playwright_smoke({})["returncode"] == 0

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args,
            2,
            stdout="not-json",
            stderr="boom",
        ),
    )
    failed = smoke.run_node_artifact_lifecycle_playwright_smoke({})
    assert failed["failure_code"] == "node_playwright_failed"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            stdout="not-json",
            stderr="",
        ),
    )
    invalid_json = smoke.run_node_artifact_lifecycle_playwright_smoke({})
    assert invalid_json["failure_code"] == "node_json_invalid"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            stdout="[1, 2, 3]",
            stderr="",
        ),
    )
    invalid = smoke.run_node_artifact_lifecycle_playwright_smoke({})
    assert invalid["failure_code"] == "node_payload_invalid"


def test_artifact_lifecycle_playwright_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = enabled_env()
    env[smoke.PROXY_TARGET_ENV] = "http://127.0.0.1:9999"

    assert smoke._node_environ(
        {
            smoke.CHROMIUM_EXECUTABLE_ENV: "/usr/bin/chromium",
            smoke.TIMEOUT_MS_ENV: "45000",
        },
        web_url="http://127.0.0.1:5458/",
        artifact_id="artifact-0458",
    ) == {
        "NEX_AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_WEB_URL": (
            "http://127.0.0.1:5458/"
        ),
        "NEX_AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_ARTIFACT_ID": (
            "artifact-0458"
        ),
        smoke.CHROMIUM_EXECUTABLE_ENV: "/usr/bin/chromium",
        smoke.TIMEOUT_MS_ENV: "45000",
    }
    assert smoke._source_status(None, version_key="x") == {"status": "NOT_RUN"}
    assert smoke._source_status({"status": "FAIL", "failure_code": "bad"}, version_key="x") == {
        "status": "FAIL",
        "failure_code": "bad",
    }
    assert smoke._safe_source_detail({"status": "FAIL", "failure_code": "bad"}) == (
        "source_status=FAIL source_failure_code=bad"
    )
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="server-only"):
        smoke.assert_smoke_evidence_redacted("Move out of active view", {})

    output_path = tmp_path / "evidence.json"
    evidence = run_with_injected_runtime()
    smoke.write_smoke_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_lifecycle_playwright_postgres_smoke",
        lambda: evidence,
    )
    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_web_artifact_lifecycle_playwright_postgres_smoke=pass" in (
        capsys.readouterr().out
    )

    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_lifecycle_playwright_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "checks_failed"},
    )
    assert smoke.main(["--summary"]) == 1

    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_lifecycle_playwright_postgres_smoke",
        lambda: (_ for _ in ()).throw(ValueError("redaction")),
    )
    assert smoke.main(["--summary"]) == 1


def test_artifact_lifecycle_prepared_cleanup_and_db_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_calls: list[dict[str, list[str]]] = []

    monkeypatch.setattr(
        smoke.collection_pg,
        "_cleanup_smoke_rows",
        lambda _engine, *, artifact_ids, artifact_handoff_ids: cleanup_calls.append(
            {
                "artifact_ids": artifact_ids,
                "artifact_handoff_ids": artifact_handoff_ids,
            }
        )
        or {"artifacts": len(artifact_ids), "handoffs": len(artifact_handoff_ids)},
    )
    tempdir = tempfile.TemporaryDirectory(prefix="nex-test-prepared-lifecycle-")
    prepared = smoke.PreparedArtifactLifecyclePlaywrightPostgresSmoke(
        profile="test",
        request_id="request-cleanup",
        trace_id="trace-cleanup",
        database_env="NEX_AE_TEST_DATABASE_URL",
        redacted_database_url="postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test",
        migration={"service_id": "nex-ae-api"},
        engine=object(),
        ae_app=object(),
        tenant_id="tenant-cleanup",
        workspace_id="workspace-cleanup",
        owner_user_id="owner-cleanup",
        artifact_handoff_id="handoff-cleanup",
        artifact_id="artifact-cleanup",
        materialized_file_count=1,
        storage_tempdir=tempdir,
    )

    assert prepared.cleanup() == {"artifacts": 1, "handoffs": 1}
    assert cleanup_calls == [
        {
            "artifact_ids": ["artifact-cleanup"],
            "artifact_handoff_ids": ["handoff-cleanup"],
        }
    ]

    monkeypatch.setattr(
        smoke.lifecycle_pg,
        "_db_observations",
        lambda _engine, **kwargs: {"deleted_rows": 1, "kwargs": kwargs},
    )
    observations = smoke.latest_artifact_lifecycle_observations(
        object(),
        artifact_id="artifact-cleanup",
        tenant_id="tenant-cleanup",
        workspace_id="workspace-cleanup",
        owner_user_id="owner-cleanup",
    )
    assert observations["deleted_rows"] == 1
    assert observations["kwargs"]["artifact_id"] == "artifact-cleanup"
