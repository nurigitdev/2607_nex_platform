from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import run_ae_artifact_export_postgres_smoke as smoke
from run_migrations import MigrationError
from test_ae_artifact_postgres_smoke import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0426@127.0.0.1:5432/nex_ae_test"
        ),
    }


def test_ae_artifact_export_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_artifact_export_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["skip_reason"] == f"{smoke.SMOKE_ENV} is not enabled."
    assert smoke.summary_line(evidence) == (
        f"ae_artifact_export_postgres_smoke=skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_export_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_artifact_export_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_export_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_export_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_artifact_export_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_export_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_artifact_export_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0426" not in evidence["detail"]


def test_ae_artifact_export_postgres_smoke_reports_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_export_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom nuri1004")),
    )

    evidence = smoke.run_ae_artifact_export_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert "nuri1004" not in evidence["detail"]


def test_ae_artifact_export_postgres_smoke_passes_multi_format_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=(smoke.artifact_smoke.MIGRATION_VERSION,),
            applied=(),
            skipped=(smoke.artifact_smoke.MIGRATION_VERSION,),
        ),
    )

    evidence = smoke.run_ae_artifact_export_postgres_smoke(smoke_env())
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["formats"] == ["MD", "HTML_PREVIEW", "DOCX", "PDF"]
    assert evidence["download_shapes"] == {
        "MD": "text",
        "HTML_PREVIEW": "text",
        "DOCX": "base64",
        "PDF": "base64",
    }
    assert evidence["db_observations"]["file_count"] == 4
    assert evidence["db_observations"]["link_count"] == 8
    assert evidence["read_model_observations"]["artifact_detail_file_count"] == 4
    assert (
        evidence["read_model_observations"]["artifact_detail_download_link_count"] == 4
    )
    assert evidence["read_model_observations"]["versions_current_rendered_formats"] == [
        "MD",
        "HTML_PREVIEW",
        "DOCX",
        "PDF",
    ]
    assert evidence["read_model_observations"]["render_job_status"] == "COMPLETED"
    assert evidence["storage"]["materialized_extensions"] == [
        "docx",
        "html",
        "md",
        "pdf",
    ]
    assert all(evidence["checks"].values())
    assert (
        "formats=MD,HTML_PREVIEW,DOCX,PDF files=4 links=8 read_model_files=4"
        in smoke.summary_line(evidence)
    )
    assert "secret-0426" not in serialized
    assert "/data/nex-platform" not in serialized


def test_ae_artifact_export_postgres_smoke_execute_reports_route_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke, "register_artifact_handoff_routes", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="handoff route failed"):
        smoke._execute_ae_artifact_export_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )

    def handoff_only(app: Any, **_: Any) -> None:
        @app.post("/api/v1/artifact-handoffs")
        def create_handoff() -> dict[str, str]:
            return {"artifact_handoff_id": "handoff-route-failure"}

    monkeypatch.setattr(smoke, "register_artifact_handoff_routes", handoff_only)
    with pytest.raises(RuntimeError, match="create route failed"):
        smoke._execute_ae_artifact_export_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )

    def handoff_and_artifact(app: Any, **_: Any) -> None:
        @app.post("/api/v1/artifact-handoffs")
        def create_handoff() -> dict[str, str]:
            return {"artifact_handoff_id": "handoff-route-failure"}

        @app.post("/api/v1/artifacts")
        def create_artifact() -> dict[str, str]:
            return {"artifact_id": "artifact-route-failure"}

    monkeypatch.setattr(smoke, "register_artifact_handoff_routes", handoff_and_artifact)
    with pytest.raises(RuntimeError, match="render route failed"):
        smoke._execute_ae_artifact_export_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_export_postgres_smoke_execute_wraps_sqlalchemy_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenEngine:
        def begin(self) -> Any:
            raise smoke.SQLAlchemyError("cleanup skipped")

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: BrokenEngine())

    with pytest.raises(RuntimeError, match="broken session"):
        monkeypatch.setattr(
            smoke,
            "build_session_factory",
            lambda _engine: (_ for _ in ()).throw(ValueError("broken session")),
        )
        smoke._execute_ae_artifact_export_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_export_postgres_smoke_execute_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_export_db_observations",
        lambda *args, **kwargs: {
            "artifact_status": "READY",
            "render_job_status": "COMPLETED",
            "rendered_formats": ["MD"],
            "file_formats": ["MD"],
            "file_count": 1,
            "link_count": 2,
            "mime_types": {"MD": "text/markdown"},
            "file_size_bytes": {"MD": 12},
        },
    )

    with pytest.raises(RuntimeError, match="db_rendered_formats"):
        smoke._execute_ae_artifact_export_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_export_postgres_smoke_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert smoke._json_array('["MD", "PDF"]') == ["MD", "PDF"]
    assert smoke._json_array(["DOCX"]) == ["DOCX"]
    assert smoke._json_array({"not": "array"}) == []
    assert smoke._response_payload(SimpleNamespace(status_code=409, json=lambda: {})) == {}
    assert smoke._response_payload(SimpleNamespace(status_code=200, json=lambda: [])) == {}
    assert smoke._response_payload(
        SimpleNamespace(status_code=200, json=lambda: {"ok": True})
    ) == {"ok": True}
    assert smoke._version_rendered_formats(
        {"versions": [{"artifact_version_id": "v1", "rendered_formats": ["PDF"]}]},
        artifact_version_id="v1",
    ) == ["PDF"]
    assert (
        smoke._version_rendered_formats(
            {"versions": [{"artifact_version_id": "v2", "rendered_formats": ["PDF"]}]},
            artifact_version_id="v1",
        )
        == []
    )
    assert (
        smoke._version_rendered_formats({"versions": "bad"}, artifact_version_id="v1")
        == []
    )
    assert smoke._read_model_observations(
        artifact_payload={
            "files": [{"format": "PDF"}, {"missing": True}, "bad"],
            "links": [{"link_type": "download"}, {"link_type": "preview"}, "bad"],
        },
        versions_payload={
            "versions": [{"artifact_version_id": "v1", "rendered_formats": '["PDF"]'}]
        },
        render_job_payload={"job_status": "COMPLETED", "current_stage": "FINALIZING"},
        artifact_status_code=200,
        versions_status_code=200,
        render_job_status_code=200,
        artifact_version_id="v1",
    ) == {
        "artifact_detail_status_code": 200,
        "versions_status_code": 200,
        "render_job_status_code": 200,
        "artifact_detail_file_count": 3,
        "artifact_detail_formats": ["PDF"],
        "artifact_detail_download_link_count": 1,
        "versions_current_rendered_formats": ["PDF"],
        "render_job_status": "COMPLETED",
        "render_job_current_stage": "FINALIZING",
    }
    assert smoke._download_shape("DOCX", {"content_encoding": "base64"}) == "invalid"
    assert smoke._download_shape("PDF", {"content": "plain"}) == "invalid"
    assert smoke._download_shape(
        "DOCX",
        {
            "content_encoding": "base64",
            "content_base64": "bm90LWEtZG9jeC1maWxl",
        },
    ) == "invalid"
    assert smoke._download_shape(
        "PDF",
        {
            "content_encoding": "base64",
            "content_base64": "bm90LWEtcGRmLWZpbGU=",
        },
    ) == "invalid"
    assert "secret-0426" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    assert smoke._redaction_safe({"ok": True}, forbidden_fragments=["secret"])
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="NEX_AE_ARTIFACT_STORAGE_ROOT"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=nuri1004", {})
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/private", {})
    with smoke._temporary_env("NEX_AE_ARTIFACT_STORAGE_ROOT", "during"):
        assert smoke.os.environ["NEX_AE_ARTIFACT_STORAGE_ROOT"] == "during"
    monkeypatch.setenv("NEX_AE_ARTIFACT_STORAGE_ROOT", "before")
    with smoke._temporary_env("NEX_AE_ARTIFACT_STORAGE_ROOT", "during"):
        assert smoke.os.environ["NEX_AE_ARTIFACT_STORAGE_ROOT"] == "during"
    assert smoke.os.environ["NEX_AE_ARTIFACT_STORAGE_ROOT"] == "before"

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_export_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_artifact_export_postgres_smoke=skipped" in capsys.readouterr().out
