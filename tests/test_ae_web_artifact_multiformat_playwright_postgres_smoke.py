from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

import run_ae_web_artifact_multiformat_playwright_postgres_smoke as smoke


EXPECTED_ROW_COUNTS = {
    "handoffs": 1,
    "artifacts": 1,
    "source_refs": 1,
    "versions": 1,
    "render_jobs": 1,
    "files": 4,
    "links": 8,
}


class FakePrepared:
    profile = "test"
    request_id = "request-0439"
    trace_id = "trace0439"
    database_env = "NEX_AE_TEST_DATABASE_URL"
    redacted_database_url = (
        "postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test"
    )
    migration = {"service_id": "nex-ae-api", "profile": "test"}
    ae_app = object()
    artifact_handoff_id = "handoff-0439"
    artifact_id = "artifact-0439"
    artifact_version_id = "artifact-version-0439"
    render_job_id = "render-job-0439"
    primary_artifact_file_id = "artifact-file-0439-md"
    file_ids_by_format = {
        "MD": "artifact-file-0439-md",
        "HTML_PREVIEW": "artifact-file-0439-html",
        "DOCX": "artifact-file-0439-docx",
        "PDF": "artifact-file-0439-pdf",
    }
    materialized_file_count = 4
    materialized_extensions = ["docx", "html", "md", "pdf"]
    db_observations = {}
    read_model_observations = {
        "artifact_detail_file_count": 4,
        "artifact_detail_download_link_count": 4,
        "versions_current_rendered_formats": ["MD", "HTML_PREVIEW", "DOCX", "PDF"],
        "render_job_status": "COMPLETED",
    }

    def __init__(self) -> None:
        self.cleaned = False
        self.disposed = False
        self.storage_tempdir = tempfile.TemporaryDirectory(
            prefix="nex-test-artifact-multiformat-playwright-"
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
            "postgresql+psycopg://nex_ae_user:secret-0439@127.0.0.1:5432/nex_ae_test"
        ),
    }


def readiness_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "readiness_schema_version": "ae_web_playwright_readiness.v1",
        "status": "PASS",
    }


def api_export_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "smoke_schema_version": "ae_artifact_export_postgres_smoke.v1",
        "status": "PASS",
        "formats": ["MD", "HTML_PREVIEW", "DOCX", "PDF"],
    }


def boundary_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "boundary_schema_version": "ae_web_same_origin_runtime_boundary.v1",
        "status": "PASS",
    }


def node_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "smoke_schema_version": smoke.base_playwright.NODE_SMOKE_SCHEMA_VERSION,
        "status": "PASS",
        "browser_observations": {
            "artifact_status": "READY",
            "version_panel_status": "VERSION_READY",
            "preview_panel_status": "PREVIEW_READY",
            "download_panel_status": "DOWNLOAD_READY",
            "download_save_status": "SAVED",
            "export_result_status": "SAVED",
            "download_selector_status": "READY",
            "download_selector_enabled_options": 4,
            "raw_download_retrieved": True,
            "downloaded_content_rendered": False,
        },
        "artifact": {
            "summary": {
                "artifact_id": "artifact-0439",
                "status": "READY",
                "content_included": False,
                "download_route_count": 4,
                "available_format_count": 4,
            },
            "version_panel": {
                "status": "VERSION_READY",
                "version_count": 1,
                "file_count": 4,
                "format_count": 4,
                "formats": ["MD", "HTML_PREVIEW", "DOCX", "PDF"],
                "preview_route_count": 4,
                "download_route_count": 4,
            },
            "download_selector": {
                "status": "READY",
                "primary_format": "MD",
                "selected_format": "MD",
                "option_count": 4,
                "enabled_option_count": 4,
                "disabled_option_count": 0,
                "selected_route_present": True,
                "selected_artifact_file_id": "artifact-file-0439-md",
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
                "downloadable_format_count": 4,
            },
        },
        "request_observations": {
            "ae_api_request_count": 5,
            "ae_api_response_count": 5,
            "request_routes": [],
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
            "browser_file_save_prepared": True,
            "artifact_download_selector_ready": True,
            "raw_download_retrieved_but_not_rendered": True,
        },
    }


def artifact_observations(_engine: object, **_kwargs: object) -> dict[str, Any]:
    return {
        "row_counts": EXPECTED_ROW_COUNTS,
        "rendered_formats": ["MD", "HTML_PREVIEW", "DOCX", "PDF"],
        "file_formats": ["MD", "HTML_PREVIEW", "DOCX", "PDF"],
        "file_count": 4,
        "link_count": 8,
        "download_link_count": 4,
        "preview_link_count": 4,
    }


def started(url: str) -> smoke.login_pg.StartedServer:
    return smoke.login_pg.StartedServer(url=url, stop=lambda: None)


def run_with_injected_runtime(
    *,
    prepared: FakePrepared | None = None,
    node_runner=node_pass,
    readiness_runner=readiness_pass,
    api_export_runner=api_export_pass,
    boundary_runner=boundary_pass,
) -> dict[str, Any]:
    prepared = prepared or FakePrepared()
    return smoke.run_ae_web_artifact_multiformat_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=readiness_runner,
        api_export_runner=api_export_runner,
        boundary_runner=boundary_runner,
        prepare_runner=lambda _env, _profile: prepared,
        node_runner=node_runner,
        artifact_observer=artifact_observations,
        port_allocator=iter([18039, 15239]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )


def test_artifact_multiformat_playwright_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_web_artifact_multiformat_playwright_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        "ae_web_artifact_multiformat_playwright_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_artifact_multiformat_playwright_postgres_smoke_passes_with_injected_runtime() -> None:
    prepared = FakePrepared()

    evidence = run_with_injected_runtime(prepared=prepared)
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["checks"]["api_export_postgres_passed"] is True
    assert evidence["checks"]["browser_download_selector_multiformat"] is True
    assert evidence["checks"]["postgres_multiformat_rows_persisted"] is True
    assert evidence["artifact"]["download_selector"]["enabled_option_count"] == 4
    assert evidence["artifact"]["version_panel"]["file_count"] == 4
    assert evidence["storage"]["materialized_file_count"] == 4
    assert evidence["cleanup_observations"] == {"artifacts": 1, "handoffs": 1}
    assert prepared.cleaned is True
    assert prepared.disposed is True
    assert "secret-0439" not in serialized
    assert smoke.summary_line(evidence) == (
        "ae_web_artifact_multiformat_playwright_postgres_smoke=pass "
        "profile=test artifact=artifact-0439 selector=READY enabled=4 "
        "formats=4 files=4 links=8 rows=17 live_db=true browser=playwright"
    )


def test_artifact_multiformat_playwright_postgres_smoke_reports_failures() -> None:
    env = enabled_env()
    readiness_failed = smoke.run_ae_web_artifact_multiformat_playwright_postgres_smoke(
        env,
        readiness_runner=lambda _env: {"status": "FAIL", "readiness_schema_version": "x"},
    )
    api_failed = smoke.run_ae_web_artifact_multiformat_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        api_export_runner=lambda _env: {
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
    config_failed = smoke.run_ae_web_artifact_multiformat_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        api_export_runner=api_export_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(ValueError("bad")),
    )
    execution_failed = smoke.run_ae_web_artifact_multiformat_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        api_export_runner=api_export_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert smoke.run_ae_web_artifact_multiformat_playwright_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )["failure_code"] == "profile_not_allowed"
    assert readiness_failed["failure_code"] == "readiness_failed"
    assert api_failed["failure_code"] == "api_export_postgres_failed"
    assert api_failed["detail"] == (
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


def test_artifact_multiformat_playwright_postgres_smoke_reports_check_failures() -> None:
    def weak_observations(_engine: object, **_kwargs: object) -> dict[str, Any]:
        return {
            **artifact_observations(_engine),
            "row_counts": {**EXPECTED_ROW_COUNTS, "files": 3},
            "file_count": 3,
            "file_formats": ["MD", "DOCX", "PDF"],
        }

    evidence = smoke.run_ae_web_artifact_multiformat_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=readiness_pass,
        api_export_runner=api_export_pass,
        boundary_runner=boundary_pass,
        prepare_runner=lambda _env, _profile: FakePrepared(),
        node_runner=lambda _env: {
            **node_pass(_env),
            "artifact": {
                **node_pass(_env)["artifact"],
                "download_selector": {
                    **node_pass(_env)["artifact"]["download_selector"],
                    "enabled_option_count": 3,
                },
            },
        },
        artifact_observer=weak_observations,
        port_allocator=iter([18039, 15239]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )

    assert evidence["status"] == "FAIL"
    failed = {issue["subject"] for issue in evidence["issues"]}
    assert "browser_download_selector_multiformat" in failed
    assert "postgres_multiformat_rows_persisted" in failed


def test_artifact_multiformat_playwright_helpers_redaction_output_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "evidence.json"
    evidence = {"status": "PASS", "profile": "test"}

    smoke.write_smoke_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"
    assert smoke._json_array('["MD", "PDF"]') == ["MD", "PDF"]
    assert smoke._json_array(["DOCX"]) == ["DOCX"]
    assert smoke._json_array({"no": "array"}) == []
    assert smoke._mapping({"ok": True}) == {"ok": True}
    assert smoke._mapping([]) == {}
    assert smoke._source_status(None, version_key="x") == {"status": "NOT_RUN"}
    assert smoke._source_status(
        {"status": "FAIL", "failure_code": "x"},
        version_key="missing",
    ) == {"status": "FAIL", "failure_code": "x"}
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(
            enabled_env()["NEX_AE_TEST_DATABASE_URL"],
            enabled_env(),
        )

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_multiformat_playwright_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "not enabled"},
    )
    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_multiformat_playwright_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "x"},
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=x" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_multiformat_playwright_postgres_smoke",
        lambda: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main([]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_artifact_multiformat_node_runner_is_still_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def completed(returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["node"], returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(
        smoke.base_playwright.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, json.dumps(node_pass({}))),
    )

    assert smoke.base_playwright.run_node_playwright_artifact_smoke({})["status"] == "PASS"


def test_artifact_multiformat_prepared_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    cleanup_calls: list[dict[str, object]] = []
    temp_dir = tempfile.TemporaryDirectory(
        prefix="nex-test-artifact-multiformat-playwright-"
    )
    prepared = smoke.PreparedArtifactMultiformatPlaywrightPostgresSmoke(
        profile="test",
        request_id="request-0439",
        trace_id="trace0439",
        database_env="NEX_AE_TEST_DATABASE_URL",
        redacted_database_url="redacted",
        migration={},
        engine="engine",
        ae_app=object(),
        artifact_handoff_id="handoff",
        artifact_id="artifact",
        artifact_version_id="version",
        render_job_id="render-job",
        primary_artifact_file_id="file-md",
        file_ids_by_format={"MD": "file-md"},
        materialized_file_count=1,
        materialized_extensions=["md"],
        db_observations={},
        read_model_observations={},
        storage_tempdir=temp_dir,
    )
    monkeypatch.setattr(
        smoke.artifact_pg,
        "_cleanup_smoke_rows",
        lambda engine, **kwargs: cleanup_calls.append({"engine": engine, **kwargs})
        or {"artifacts": 1, "handoffs": 1},
    )

    assert prepared.cleanup() == {"artifacts": 1, "handoffs": 1}
    assert cleanup_calls == [
        {
            "engine": "engine",
            "artifact_id": "artifact",
            "artifact_handoff_id": "handoff",
        }
    ]
