from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

import run_ae_web_artifact_library_playwright_postgres_smoke as smoke


class FakePrepared:
    profile = "test"
    request_id = "request-0448"
    trace_id = "trace0448"
    database_env = "NEX_AE_TEST_DATABASE_URL"
    redacted_database_url = (
        "postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test"
    )
    migration = {"service_id": "nex-ae-api", "profile": "test"}
    ae_app = object()
    tenant_id = "tenant-library-0448"
    workspace_id = "workspace-library-0448"
    owner_user_id = "owner-library-0448"
    ready_artifact_id = "artifact-library-ready-0448"
    draft_artifact_id = "artifact-library-draft-0448"
    other_owner_artifact_id = "artifact-library-other-0448"
    artifact_ids = [
        "artifact-library-draft-0448",
        "artifact-library-ready-0448",
        "artifact-library-other-0448",
    ]
    artifact_handoff_ids = [
        "handoff-library-draft-0448",
        "handoff-library-ready-0448",
        "handoff-library-other-0448",
    ]
    materialized_file_count = 2
    db_observations = {}

    def __init__(self) -> None:
        self.cleaned = False
        self.disposed = False
        self.storage_tempdir = tempfile.TemporaryDirectory(
            prefix="nex-test-artifact-library-playwright-"
        )
        self.engine = type(
            "FakeEngine",
            (),
            {"dispose": lambda inner_self: setattr(self, "disposed", True)},
        )()

    def cleanup(self) -> dict[str, int]:
        self.cleaned = True
        self.storage_tempdir.cleanup()
        return {"artifacts": 3, "handoffs": 3}


def enabled_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0448@127.0.0.1:5432/nex_ae_test"
        ),
    }


def readiness_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "readiness_schema_version": "ae_web_playwright_readiness.v1",
        "status": "PASS",
    }


def collection_pass(_env: dict[str, str]) -> dict[str, Any]:
    return {
        "smoke_schema_version": "ae_artifact_collection_postgres_smoke.v1",
        "status": "PASS",
        "collection": {"count": 2, "ready_count": 1},
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
            "artifact_library_shell_dom_present": True,
            "library_status": "READY",
            "library_item_count": 2,
            "ready_count": 1,
            "downloadable_count": 1,
            "previewable_count": 1,
            "rendered_item_count": 2,
            "ready_artifact_rendered": True,
        },
        "library": {
            "collection_summary": {
                "item_count": 2,
                "ready_count": 1,
                "filter": {
                    "tenant_id": "tenant-library-0448",
                    "workspace_id": "workspace-library-0448",
                    "owner_user_id": "owner-library-0448",
                },
            },
            "panel_summary": {
                "status": "READY",
                "item_count": 2,
                "ready_count": 1,
                "downloadable_count": 1,
                "previewable_count": 1,
            },
            "selected_artifact_summary": {
                "artifact_id": "artifact-library-ready-0448",
                "status": "READY",
                "content_included": False,
            },
        },
        "request_observations": {
            "ae_api_request_count": 2,
            "ae_api_response_count": 2,
            "request_routes": [
                {"method": "GET", "route": "/ae-api/api/v1/artifacts?limit=20"},
                {
                    "method": "GET",
                    "route": "/ae-api/api/v1/artifacts/artifact-library-ready-0448",
                },
            ],
            "response_routes": [],
        },
        "checks": {
            "playwright_browser_launched": True,
            "artifact_collection_called": True,
            "artifact_detail_called": True,
            "browser_request_secret_header_absent": True,
            "artifact_library_panel_ready": True,
            "artifact_library_owner_scoped": True,
            "artifact_library_ready_filter": True,
            "artifact_library_failed_filter_empty": True,
            "artifact_library_downloadable_filter": True,
            "artifact_library_previewable_filter": True,
            "artifact_library_dom_rendered": True,
            "selected_artifact_detail_ready": True,
            "artifact_library_metadata_only": True,
        },
    }


def artifact_observations(_engine: object, **_kwargs: object) -> dict[str, Any]:
    return {
        "owner_rows": 2,
        "ready_rows": 1,
        "other_owner_rows": 1,
        "indexes_present": sorted(smoke.collection_pg.EXPECTED_COLLECTION_INDEXES),
    }


def started(url: str) -> smoke.login_pg.StartedServer:
    return smoke.login_pg.StartedServer(url=url, stop=lambda: None)


def run_with_injected_runtime(
    *,
    prepared: FakePrepared | None = None,
    node_runner=node_pass,
    readiness_runner=readiness_pass,
    collection_runner=collection_pass,
    boundary_runner=boundary_pass,
    artifact_observer=artifact_observations,
) -> dict[str, Any]:
    prepared = prepared or FakePrepared()
    return smoke.run_ae_web_artifact_library_playwright_postgres_smoke(
        enabled_env(),
        readiness_runner=readiness_runner,
        collection_runner=collection_runner,
        boundary_runner=boundary_runner,
        prepare_runner=lambda _env, _profile: prepared,
        node_runner=node_runner,
        artifact_observer=artifact_observer,
        port_allocator=iter([18048, 15248]).__next__,
        api_server_starter=lambda _app, port: started(f"http://127.0.0.1:{port}"),
        web_server_starter=lambda port, _api_url: started(f"http://127.0.0.1:{port}/"),
    )


def test_artifact_library_playwright_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_web_artifact_library_playwright_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        "ae_web_artifact_library_playwright_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_artifact_library_playwright_postgres_smoke_passes_with_injected_runtime() -> None:
    prepared = FakePrepared()
    evidence = run_with_injected_runtime(prepared=prepared)
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["checks"]["artifact_collection_postgres_passed"] is True
    assert evidence["checks"]["browser_artifact_library_panel_ready"] is True
    assert evidence["checks"]["ae_test_database_connected"] is True
    assert evidence["artifact_library"]["ready_artifact_id"] == (
        "artifact-library-ready-0448"
    )
    assert evidence["db_observations"]["owner_rows"] == 2
    assert evidence["cleanup_observations"] == {"artifacts": 3, "handoffs": 3}
    assert prepared.cleaned is True
    assert prepared.disposed is True
    assert "secret-0448" not in serialized
    assert smoke.summary_line(evidence) == (
        "ae_web_artifact_library_playwright_postgres_smoke=pass "
        "profile=test items=2 ready=1 downloadable=1 owner_rows=2 "
        "other_owner_rows=1 live_db=true browser=playwright"
    )


def test_artifact_library_playwright_postgres_smoke_reports_failures() -> None:
    env = enabled_env()
    readiness_failed = smoke.run_ae_web_artifact_library_playwright_postgres_smoke(
        env,
        readiness_runner=lambda _env: {"status": "FAIL", "readiness_schema_version": "x"},
    )
    collection_failed = smoke.run_ae_web_artifact_library_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        collection_runner=lambda _env: {
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
    check_failed = run_with_injected_runtime(
        artifact_observer=lambda _engine, **_kwargs: {
            **artifact_observations(_engine),
            "owner_rows": 1,
        }
    )
    config_failed = smoke.run_ae_web_artifact_library_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        collection_runner=collection_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(ValueError("bad")),
    )
    execution_failed = smoke.run_ae_web_artifact_library_playwright_postgres_smoke(
        env,
        readiness_runner=readiness_pass,
        collection_runner=collection_pass,
        prepare_runner=lambda _env, _profile: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert smoke.run_ae_web_artifact_library_playwright_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )["failure_code"] == "profile_not_allowed"
    assert readiness_failed["failure_code"] == "readiness_failed"
    assert collection_failed["failure_code"] == "artifact_collection_postgres_failed"
    assert collection_failed["detail"] == (
        "source_status=FAIL source_failure_code=configuration_invalid"
    )
    assert boundary_failed["failure_code"] == "same_origin_boundary_failed"
    assert node_failed["status"] == "FAIL"
    assert any(
        issue["subject"] == "node_playwright_smoke_passed"
        for issue in node_failed["issues"]
    )
    assert check_failed["status"] == "FAIL"
    assert any(
        issue["subject"] == "ae_test_database_connected"
        for issue in check_failed["issues"]
    )
    assert config_failed["failure_code"] == "configuration_invalid"
    assert execution_failed["failure_code"] == "execution_failed"


def test_artifact_library_playwright_node_runner_parses_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def completed(returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["node"], returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, json.dumps(node_pass({}))),
    )
    assert smoke.run_node_artifact_library_playwright_smoke({})["status"] == "PASS"

    monkeypatch.setattr(smoke.subprocess, "run", lambda *_args, **_kwargs: completed(1, ""))
    assert (
        smoke.run_node_artifact_library_playwright_smoke({})["failure_code"]
        == "node_playwright_failed"
    )

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(0, "not-json"),
    )
    assert (
        smoke.run_node_artifact_library_playwright_smoke({})["failure_code"]
        == "node_json_invalid"
    )

    monkeypatch.setattr(smoke.subprocess, "run", lambda *_args, **_kwargs: completed(0, "[]"))
    assert (
        smoke.run_node_artifact_library_playwright_smoke({})["failure_code"]
        == "node_payload_invalid"
    )


def test_artifact_library_playwright_helpers_redaction_output_and_main(
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
            smoke.TIMEOUT_MS_ENV: "26000",
        },
        web_url="http://127.0.0.1:5448/",
        tenant_id="tenant-library-0448",
        workspace_id="workspace-library-0448",
        owner_user_id="owner-library-0448",
        ready_artifact_id="artifact-library-ready-0448",
    )

    assert node_env[smoke.CHROMIUM_EXECUTABLE_ENV] == "/usr/bin/google-chrome"
    assert node_env[smoke.TIMEOUT_MS_ENV] == "26000"
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
    with pytest.raises(ValueError, match="server-only"):
        smoke.assert_smoke_evidence_redacted("unsafe /data/nex-platform", {})

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_library_playwright_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "not enabled"},
    )
    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_library_playwright_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "x"},
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=x" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_artifact_library_playwright_postgres_smoke",
        lambda: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main([]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_artifact_library_playwright_prepared_cleanup_and_wiring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_calls: list[dict[str, object]] = []
    temp_dir = tempfile.TemporaryDirectory(
        prefix="nex-test-artifact-library-playwright-"
    )
    prepared = smoke.PreparedArtifactLibraryPlaywrightPostgresSmoke(
        profile="test",
        request_id="request-0448",
        trace_id="trace0448",
        database_env="NEX_AE_TEST_DATABASE_URL",
        redacted_database_url="redacted",
        migration={},
        engine="engine",
        ae_app=object(),
        tenant_id="tenant-library-0448",
        workspace_id="workspace-library-0448",
        owner_user_id="owner-library-0448",
        ready_artifact_id="artifact-ready",
        draft_artifact_id="artifact-draft",
        other_owner_artifact_id="artifact-other",
        artifact_ids=["artifact-draft", "artifact-ready", "artifact-other"],
        artifact_handoff_ids=["handoff-draft", "handoff-ready", "handoff-other"],
        materialized_file_count=2,
        db_observations={},
        storage_tempdir=temp_dir,
    )
    monkeypatch.setattr(
        smoke.collection_pg,
        "_cleanup_smoke_rows",
        lambda engine, **kwargs: cleanup_calls.append({"engine": engine, **kwargs})
        or {"artifacts": 3, "handoffs": 3},
    )

    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    package = json.loads(
        (root / "apps" / "nex-ae-web" / "package.json").read_text(
            encoding="utf-8"
        )
    )

    assert prepared.cleanup() == {"artifacts": 3, "handoffs": 3}
    assert cleanup_calls == [
        {
            "engine": "engine",
            "artifact_ids": ["artifact-draft", "artifact-ready", "artifact-other"],
            "artifact_handoff_ids": [
                "handoff-draft",
                "handoff-ready",
                "handoff-other",
            ],
        }
    ]
    assert (
        "run_ae_web_artifact_library_playwright_postgres_smoke.py --summary"
        in quality_gate
    )
    assert (
        package["scripts"]["smoke:artifact-library-playwright"]
        == "node scripts/runArtifactLibraryPlaywrightSmoke.mjs --summary"
    )
