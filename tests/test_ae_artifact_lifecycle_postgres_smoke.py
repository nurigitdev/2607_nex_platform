from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_lifecycle_postgres_smoke as smoke
from run_migrations import MigrationError
from test_ae_artifact_collection_postgres_smoke import FakeConnection, FakeEngine
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0454@127.0.0.1:5432/nex_ae_test"
        ),
    }


class FailingReadbackClient:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def get(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(status_code=self.status_code)


def test_ae_artifact_lifecycle_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_artifact_lifecycle_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        f"ae_artifact_lifecycle_postgres_smoke=skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_lifecycle_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_artifact_lifecycle_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_lifecycle_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_lifecycle_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_artifact_lifecycle_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_lifecycle_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_artifact_lifecycle_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0454" not in evidence["detail"]


def test_ae_artifact_lifecycle_postgres_smoke_passes_with_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("0406_ae_artifact_handoff_trace_request_columns",),
            applied=(),
            skipped=("0406_ae_artifact_handoff_trace_request_columns",),
        ),
    )

    evidence = smoke.run_ae_artifact_lifecycle_postgres_smoke(smoke_env())
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["lifecycle"] == {
        "archive_status": "ARCHIVED",
        "restore_status": "READY",
        "delete_status": "DELETED",
        "deleted_collection_count": 1,
        "ready_collection_count": 0,
    }
    assert evidence["db_observations"]["deleted_rows"] == 1
    assert evidence["db_observations"]["file_rows"] >= 2
    assert evidence["materialized_file_count"] >= 2
    assert evidence["checks"]["metadata_only_evidence"] is True
    assert evidence["live_db"] is True
    assert evidence["cleanup"] == {"artifacts": 1, "handoffs": 1}
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_lifecycle_postgres_smoke=pass service=nex-ae-api"
    )
    assert "secret-0454" not in serialized
    assert "/data/nex-platform" not in serialized


def test_ae_artifact_lifecycle_postgres_smoke_execute_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    bad_observations = {
        "ready_rows": 1,
        "archived_rows": 0,
        "deleted_rows": 0,
        "file_rows": 0,
        "link_rows": 0,
    }
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: bad_observations)

    with pytest.raises(RuntimeError, match="db_deleted_rows"):
        smoke._execute_ae_artifact_lifecycle_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_lifecycle_postgres_smoke_execute_wraps_inner_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "build_session_factory",
        lambda _engine: (_ for _ in ()).throw(ValueError("bad session factory")),
    )

    with pytest.raises(RuntimeError, match="bad session factory"):
        smoke._execute_ae_artifact_lifecycle_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_lifecycle_postgres_smoke_readback_helpers_raise_on_api_failure() -> None:
    client = FailingReadbackClient(status_code=503)

    with pytest.raises(RuntimeError, match="artifact readback failed: 503"):
        smoke._get_artifact(client, {"Authorization": "Bearer token"}, "artifact-001")

    with pytest.raises(RuntimeError, match="artifact collection readback failed: 503"):
        smoke._get_collection(
            client,
            {"Authorization": "Bearer token"},
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="owner-001",
            status="DELETED",
        )


def test_ae_artifact_lifecycle_postgres_smoke_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert "secret-0454" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="NEX_AE_ARTIFACT_STORAGE_ROOT"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=nuri1004", {})
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/ae/artifacts", {})
    assert smoke._metadata_only({"ok": True}, forbidden_fragments=["secret"])
    assert smoke._count_materialized_files(tmp_path / "missing") == 0
    (tmp_path / "stored").mkdir()
    (tmp_path / "stored" / "artifact.md").write_text("# ok", encoding="utf-8")
    assert smoke._count_materialized_files(tmp_path / "stored") == 1

    assert smoke._scalar_count(
        FakeConnection(),
        "SELECT count(*) FROM ae_artifacts",
        {"owner_user_id": "owner-001"},
    ) == 2
    assert smoke._db_observations(
        FakeEngine(),
        artifact_id="artifact-001",
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="owner-001",
    ) == {
        "ready_rows": 2,
        "archived_rows": 2,
        "deleted_rows": 2,
        "file_rows": 2,
        "link_rows": 2,
    }

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_lifecycle_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_artifact_lifecycle_postgres_smoke=skipped" in capsys.readouterr().out


def test_ae_artifact_lifecycle_postgres_smoke_reports_execution_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_lifecycle_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = smoke.run_ae_artifact_lifecycle_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
