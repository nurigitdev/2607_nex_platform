from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_retention_purge_postgres_smoke as smoke
from run_migrations import MigrationError
from test_ae_artifact_collection_postgres_smoke import FakeConnection, FakeEngine
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0469@127.0.0.1:5432/nex_ae_test"
        ),
    }


def test_ae_artifact_retention_purge_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_artifact_retention_purge_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_purge_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_retention_purge_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_artifact_retention_purge_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_purge_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_retention_purge_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_artifact_retention_purge_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_retention_purge_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_artifact_retention_purge_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0469" not in evidence["detail"]


def test_ae_artifact_retention_purge_postgres_smoke_passes_with_sqlite_harness(
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

    evidence = smoke.run_ae_artifact_retention_purge_postgres_smoke(smoke_env())
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["retention"]["as_of"] == "2026-09-01T00:00:00Z"
    assert evidence["retention"]["retention_days"] == 30
    assert evidence["retention"]["dry_run_selected_count"] == 1
    assert evidence["retention"]["blocked_status"] == "BLOCKED"
    assert evidence["retention"]["approval_blocked_status"] == "BLOCKED"
    assert evidence["retention"]["approval_blocked_reason"] == (
        "operator_approval_required"
    )
    assert evidence["retention"]["executed_selected_count"] == 1
    assert evidence["retention"]["deleted_counts"] == {
        "artifacts": 1,
        "source_refs": 1,
        "versions": 1,
        "render_jobs": 1,
        "files": 2,
        "links": 4,
        "storage_files": 2,
    }
    assert evidence["db_before"]["artifact_rows"] == 2
    assert evidence["db_before"]["candidate_rows"] == 1
    assert evidence["db_after_execute"]["artifact_rows"] == 1
    assert evidence["db_after_execute"]["handoff_rows"] == 2
    assert evidence["materialized_file_count"] == {
        "before": 4,
        "after_execute": 2,
    }
    assert evidence["checks"]["metadata_only_evidence"] is True
    assert evidence["checks"]["approval_blocked_rows_retained"] is True
    assert evidence["live_db"] is True
    assert evidence["cleanup"] == {"artifacts": 1, "handoffs": 2}
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_retention_purge_postgres_smoke=pass service=nex-ae-api"
    )
    assert "secret-0469" not in serialized
    assert "/data/nex-platform" not in serialized


def test_ae_artifact_retention_purge_postgres_smoke_execute_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: {
            "artifact_rows": 0,
            "deleted_rows": 0,
            "candidate_rows": 0,
            "file_rows": 0,
            "link_rows": 0,
            "handoff_rows": 0,
        },
    )

    with pytest.raises(RuntimeError, match="initial_candidate_rows"):
        smoke._execute_ae_artifact_retention_purge_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_purge_postgres_smoke_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert smoke._database_url_password(
        "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/nex_ae_test"
    ) == "sensitive-pass"
    assert smoke._database_url_password("not-a-url") is None
    assert "secret-0469" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="NEX_AE_ARTIFACT_STORAGE_ROOT"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=secret-0469", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/ae/artifacts", {})
    assert smoke._db_observations(
        FakeEngine(),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="owner-001",
        cutoff_at="2026-08-02T00:00:00Z",
    ) == {
        "artifact_rows": 2,
        "deleted_rows": 2,
        "candidate_rows": 2,
        "file_rows": 2,
        "link_rows": 2,
        "handoff_rows": 2,
    }
    assert smoke.candidate_pg._scalar_count(
        FakeConnection(),
        "SELECT count(*) FROM ae_artifacts",
        {"owner_user_id": "owner-001"},
    ) == 2

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_purge_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_artifact_retention_purge_postgres_smoke=skipped"
        in capsys.readouterr().out
    )


def test_ae_artifact_retention_purge_postgres_smoke_reports_execution_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_retention_purge_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = smoke.run_ae_artifact_retention_purge_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
