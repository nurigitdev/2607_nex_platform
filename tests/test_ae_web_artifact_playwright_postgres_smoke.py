from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

import run_ae_web_artifact_playwright_postgres_smoke as smoke


EXPECTED_ROW_COUNTS = {
    "handoffs": 1,
    "artifacts": 1,
    "source_refs": 1,
    "versions": 1,
    "render_jobs": 1,
    "files": 1,
    "links": 2,
}


class FakePrepared:
    profile = "test"
    request_id = "request-0419"
    trace_id = "trace0419"
    database_env = "NEX_AE_TEST_DATABASE_URL"
    redacted_database_url = (
        "postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test"
    )
    migration = {"service_id": "nex-ae-api", "profile": "test"}
    engine = object()
    ae_app = object()
    artifact_handoff_id = "handoff-0419"
    artifact_id = "artifact-0419"
    artifact_version_id = "artifact-version-0419"
    render_job_id = "render-job-0419"
    artifact_file_id = "artifact-file-0419"
    markdown_file_count = 1
    db_observations = {}

    def __init__(self) -> None:
        self.cleaned = False
        self.disposed = False
        self.storage_tempdir = tempfile.TemporaryDirectory(
            prefix="nex-test-artifact-playwright-"
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
            "postgresql+psycopg://nex_ae_user:secret@127.0.0.1:5432/nex_ae_test"
        ),
    }


def readiness_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "readiness_schema_version": "ae_web_playwright_readiness.v1",
        "status": "PASS",
    }


def web_postgres_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "smoke_schema_version": "ae_web_artifact_postgres_smoke.v1",
        "status": "PASS",
        "artifact_id": "artifact-api-0418",
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
            "artifact_status": "READY",
            "version_panel_status": "VERSION_READY",
            "preview_panel_status": "PREVIEW_READY",
            "download_panel_status": "DOWNLOAD_READY",
            "download_save_status": "SAVED",
            "export_result_status": "SAVED",
            "download_selector_status": "READY",
            "download_selector_enabled_options": 1,
            "raw_download_retrieved": True,
            "downloaded_content_rendered": False,
        },
        "artifact": {
            "summary": {
                "artifact_id": "artifact-0419",
                "status": "READY",
                "content_included": False,
            },
            "version_panel": {
                "status": "VERSION_READY",
                "version_count": 1,
                "file_count": 1,
            },
            "preview_panel": {
                "status": "PREVIEW_READY",
                "metadata": {"downloadedContentRendered": False},
            },
            "download_panel": {
                "status": "DOWNLOAD_READY",
                "metadata": {"downloadedContentRendered": False},
            },
            "download_save": {
                "status": "SAVED",
                "blob_created": True,
                "object_url_created": True,
                "anchor_clicked": True,
                "object_url_revoked": True,
                "browser_save_available": True,
                "payload_kind": "text",
            },
            "export_result": {
                "status": "SAVED",
                "latest_save_status": "SAVED",
                "downloadable_format_count": 1,
            },
            "download_selector": {
                "status": "READY",
                "enabled_option_count": 1,
                "selected_route_present": True,
                "selected_artifact_file_id": "artifact-file-0419",
            },
        },
        "request_observations": {
            "ae_api_request_count": 5,
            "ae_api_response_count": 5,
            "request_routes": [
                {"method": "GET", "route": "/ae-api/api/v1/artifacts/artifact-0419"},
                {
                    "method": "GET",
                    "route": "/ae-api/api/v1/artifacts/artifact-0419/versions",
                },
                {
                    "method": "GET",
                    "route": "/ae-api/api/v1/artifact-files/artifact-file-0419",
                },
                {
                    "method": "GET",
                    "route": "/ae-api/api/v1/artifact-files/artifact-file-0419/preview",
                },
                {
                    "method": "GET",
                    "route": "/ae-api/api/v1/artifact-files/artifact-file-0419/download",
                },
            ],
            "response_routes": [],
        },
        "checks": {
            "playwright_browser_launched": True,
            "artifact_detail_called": True,
            "artifact_versions_called": True,
            "artifact_file_metadata_called": True,
            "artifact_preview_called": True,
            "artifact_download_called": True,
            "browser_request_secret_header_absent": True,
            "artifact_version_panel_ready": True,
            "artifact_preview_panel_ready": True,
            "artifact_download_panel_ready": True,
            "browser_file_save_prepared": True,
            "browser_export_result_saved": True,
            "artifact_download_selector_ready": True,
            "raw_download_retrieved_but_not_rendered": True,
        },
    }


def artifact_observations(_engine: object, **_kwargs: object) -> dict[str, Any]:
    return {
        "row_counts": EXPECTED_ROW_COUNTS,
        "migration_recorded": True,
        "tables_present_count": len(smoke.artifact_pg.EXPECTED_TABLES),
        "indexes_present_count": len(smoke.artifact_pg.EXPECTED_INDEXES),
        "jsonb_column_count": 5,
        "logical_storage_ref_present": True,
        "handoff_correlation_columns_present": True,
    }


def started(url: str) -> smoke.login_pg.StartedServer:
    return smoke.login_pg.StartedServer(url=url, stop=lambda: None)


def test_artifact_playwright_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_web_artifact_playwright_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        "ae_web_artifact_playwright_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_artifact_playwright_postgres_smoke_passes_with_injected_runtime() -> None:
    prepared = FakePrepared()

    evidence = smoke.run_ae_web_artifact_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=readiness_pass,
        web_postgres_runner=web_postgres_pass,
        boundary_runner=boundary_pass,
        prepare_runner=lambda _env, _profile: prepared,
        node_runner=node_pass,
        artifact_observer=artifact_observations,
        port_allocator=iter([18019, 15219]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["checks"]["web_artifact_postgres_passed"] is True
    assert evidence["checks"]["browser_artifact_download_called"] is True
    assert evidence["checks"]["browser_file_save_prepared"] is True
    assert evidence["artifact"]["download_save"]["status"] == "SAVED"
    assert evidence["artifact"]["export_result"]["status"] == "SAVED"
    assert evidence["checks"]["browser_download_selector_ready"] is True
    assert evidence["artifact"]["download_selector"]["status"] == "READY"
    assert evidence["checks"]["postgres_artifact_rows_persisted"] is True
    assert evidence["cleanup_observations"] == {"artifacts": 1, "handoffs": 1}
    assert prepared.cleaned is True
    assert prepared.disposed is True
    assert enabled_env()["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert "secret@127.0.0.1" not in serialized
    assert smoke.summary_line(evidence) == (
        "ae_web_artifact_playwright_postgres_smoke=pass "
        "profile=test artifact=artifact-0419 version_panel=VERSION_READY "
        "preview_panel=PREVIEW_READY download_panel=DOWNLOAD_READY "
        "download_save=SAVED export_result=SAVED "
        "selector=READY "
        "rows=8 live_db=true browser=playwright"
    )


def test_artifact_playwright_postgres_smoke_reports_failure_branches() -> None:
    env = enabled_env()

    readiness_failed = smoke.run_ae_web_artifact_playwright_postgres_smoke(
        env,
        readiness_runner=lambda _env: {"status": "FAIL", "readiness_schema_version": "x"},
    )
    web_postgres_failed = smoke.run_ae_web_artifact_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        web_postgres_runner=lambda _env: {
            "smoke_schema_version": "x",
            "status": "FAIL",
            "failure_code": "configuration_invalid",
        },
    )
    boundary_failed = smoke.run_ae_web_artifact_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        web_postgres_runner=web_postgres_pass,
        boundary_runner=lambda _env: {"status": "FAIL", "boundary_schema_version": "x"},
        prepare_runner=lambda _env, _profile: FakePrepared(),
        node_runner=node_pass,
        artifact_observer=artifact_observations,
        port_allocator=iter([18019, 15219]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )
    node_failed = smoke.run_ae_web_artifact_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        web_postgres_runner=web_postgres_pass,
        boundary_runner=boundary_pass,
        prepare_runner=lambda _env, _profile: FakePrepared(),
        node_runner=lambda _env: {**node_pass(_env), "status": "FAIL"},
        artifact_observer=artifact_observations,
        port_allocator=iter([18019, 15219]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )
    config_failed = smoke.run_ae_web_artifact_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        web_postgres_runner=web_postgres_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(ValueError("bad")),
    )
    execution_failed = smoke.run_ae_web_artifact_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        web_postgres_runner=web_postgres_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert smoke.run_ae_web_artifact_playwright_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )["failure_code"] == "profile_not_allowed"
    assert readiness_failed["failure_code"] == "readiness_failed"
    assert web_postgres_failed["failure_code"] == "web_artifact_postgres_failed"
    assert web_postgres_failed["detail"] == (
        "source_status=FAIL source_failure_code=configuration_invalid"
    )
    assert boundary_failed["failure_code"] == "same_origin_boundary_failed"
    assert node_failed["status"] == "FAIL"
    assert any(
        issue["subject"] == "node_playwright_smoke_passed"
        for issue in node_failed["issues"]
    )
    assert config_failed["failure_code"] == "configuration_invalid"
    assert execution_failed["failure_code"] == "execution_failed"


def test_artifact_playwright_node_runner_parses_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def completed(returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["node"], returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, json.dumps(node_pass({}))),
    )
    assert smoke.run_node_playwright_artifact_smoke({})["status"] == "PASS"

    monkeypatch.setattr(smoke.subprocess, "run", lambda *_args, **_kwargs: completed(1, ""))
    assert (
        smoke.run_node_playwright_artifact_smoke({})["failure_code"]
        == "node_playwright_failed"
    )

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, "not-json"),
    )
    assert smoke.run_node_playwright_artifact_smoke({})["failure_code"] == "node_json_invalid"

    monkeypatch.setattr(smoke.subprocess, "run", lambda *_args, **_kwargs: completed(0, "[]"))
    assert (
        smoke.run_node_playwright_artifact_smoke({})["failure_code"]
        == "node_payload_invalid"
    )


def test_artifact_playwright_helpers_redaction_output_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "evidence.json"
    evidence = {"status": "PASS", "profile": "test"}

    smoke.write_smoke_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    node_env = smoke._node_environ(
        {
            smoke.CHROMIUM_EXECUTABLE_ENV: "/usr/bin/google-chrome",
            smoke.TIMEOUT_MS_ENV: "22000",
        },
        web_url="http://127.0.0.1:5229/",
        artifact_id="artifact-0419",
        artifact_file_id="artifact-file-0419",
    )

    assert node_env[smoke.CHROMIUM_EXECUTABLE_ENV] == "/usr/bin/google-chrome"
    assert node_env[smoke.TIMEOUT_MS_ENV] == "22000"
    assert smoke._is_artifact_browser_path("/api/v1/artifact-files/file") is True
    assert smoke._is_artifact_browser_path("/health") is False
    assert smoke._has_header([(b"authorization", b"value")], b"authorization") is True
    assert smoke._has_header("bad", b"authorization") is False
    assert smoke._source_status({"status": "PASS"}, version_key="missing") == {
        "status": "PASS"
    }
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(
            enabled_env()["NEX_AE_TEST_DATABASE_URL"],
            enabled_env(),
        )
    with pytest.raises(ValueError, match="server-only"):
        smoke.assert_smoke_evidence_redacted("unsafe /data/nex-platform", {})

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_playwright_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "not enabled"},
    )
    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_playwright_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "x"},
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=x" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_playwright_postgres_smoke",
        lambda: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main([]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_artifact_playwright_prepared_cleanup_and_docs_are_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_calls: list[dict[str, object]] = []
    temp_dir = tempfile.TemporaryDirectory(prefix="nex-test-artifact-playwright-")
    prepared = smoke.PreparedArtifactPlaywrightPostgresSmoke(
        profile="test",
        request_id="request-0419",
        trace_id="trace0419",
        database_env="NEX_AE_TEST_DATABASE_URL",
        redacted_database_url="redacted",
        migration={},
        engine="engine",
        ae_app=object(),
        artifact_handoff_id="handoff",
        artifact_id="artifact",
        artifact_version_id="version",
        render_job_id="render-job",
        artifact_file_id="file",
        markdown_file_count=1,
        db_observations={},
        storage_tempdir=temp_dir,
    )
    monkeypatch.setattr(
        smoke.artifact_pg,
        "_cleanup_smoke_rows",
        lambda engine, **kwargs: cleanup_calls.append({"engine": engine, **kwargs})
        or {"artifacts": 1, "handoffs": 1},
    )

    cleanup = prepared.cleanup()
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    package = json.loads(
        (root / "apps" / "nex-ae-web" / "package.json").read_text(
            encoding="utf-8"
        )
    )

    assert cleanup == {"artifacts": 1, "handoffs": 1}
    assert cleanup_calls == [
        {
            "engine": "engine",
            "artifact_id": "artifact",
            "artifact_handoff_id": "handoff",
        }
    ]
    assert (
        "run_ae_web_artifact_playwright_postgres_smoke.py --summary" in quality_gate
    )
    assert "0419_ae_web_artifact_playwright_postgresql_smoke.md" in docs_index
    assert "0435_ae_web_artifact_download_playwright_postgresql_smoke.md" in docs_index
    assert package["scripts"]["smoke:artifact-playwright"]
