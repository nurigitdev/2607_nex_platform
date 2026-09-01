from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_retention_scheduled_execution_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0489@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def good_observations() -> dict[str, int]:
    return {
        "artifact_rows": 3,
        "deleted_rows": 3,
        "candidate_rows": 2,
        "file_rows": 6,
        "link_rows": 12,
    }


def test_ae_artifact_retention_scheduled_execution_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_artifact_retention_scheduled_execution_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduled_execution_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_retention_scheduled_execution_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_artifact_retention_scheduled_execution_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduled_execution_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_retention_scheduled_execution_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_artifact_retention_scheduled_execution_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_retention_scheduled_execution_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_artifact_retention_scheduled_execution_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0489" not in evidence["detail"]


def test_ae_artifact_retention_scheduled_execution_postgres_smoke_passes_with_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("0472_ae_artifact_retention_execution_history",),
            applied=(),
            skipped=("0472_ae_artifact_retention_execution_history",),
        ),
    )

    evidence = smoke.run_ae_artifact_retention_scheduled_execution_postgres_smoke(
        smoke_env()
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["batch_plan"]["plan_status"] == "READY"
    assert evidence["batch_plan"]["scheduler_status"] == "DISABLED"
    assert evidence["batch_plan"]["candidate_count"] == 2
    assert evidence["batch_plan"]["selected_count"] == 1
    assert evidence["command"] == {
        "command_status": "READY",
        "trigger_type": "scheduler_tick",
        "execution_mode": "DRY_RUN",
        "selected_count": 1,
    }
    assert evidence["worker"]["worker_status"] == "SUCCEEDED"
    assert evidence["worker"]["history_written"] is True
    assert evidence["history"]["row_count"] == 1
    assert evidence["db_before"] == good_observations()
    assert evidence["db_after_worker"] == good_observations()
    assert evidence["materialized_file_count"] == {
        "before": 6,
        "after_worker": 6,
    }
    assert evidence["ag_projection"] == {
        "projection_status": "READY",
        "dispatch_available": True,
        "selected_count": 1,
    }
    assert all(evidence["checks"].values())
    assert evidence["cleanup"] == {"artifacts": 3, "handoffs": 3, "history_rows": 1}
    assert evidence["live_db"] is True
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_retention_scheduled_execution_postgres_smoke=pass "
        "service=nex-ae-api"
    )
    assert "secret-0489" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "storage_ref" not in serialized


def test_ae_artifact_retention_scheduled_execution_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke, "_count_files", lambda _root: 0)

    with pytest.raises(RuntimeError, match="storage_files_retained"):
        smoke._execute_ae_artifact_retention_scheduled_execution_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduled_execution_postgres_smoke_wraps_execute_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "build_session_factory",
        lambda _engine: (_ for _ in ()).throw(ValueError("bad session")),
    )

    with pytest.raises(RuntimeError, match="bad session"):
        smoke._execute_ae_artifact_retention_scheduled_execution_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduled_execution_postgres_smoke_reports_execution_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_retention_scheduled_execution_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = smoke.run_ae_artifact_retention_scheduled_execution_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_artifact_retention_scheduled_execution_postgres_smoke_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"
    worker_result = {
        "execution": {
            "execution_id": "execution-0489",
            "mode": "DRY_RUN",
            "execution_status": "SUCCEEDED",
            "delete_enabled": False,
            "storage_mutation_enabled": False,
            "database_row_delete_enabled": False,
            "deleted_counts": {"artifacts": 0},
        }
    }
    history_rows = [
        {
            "retention_execution_id": "execution-0489",
            "mode": "DRY_RUN",
            "execution_status": "SUCCEEDED",
            "execution": {"execution_id": "execution-0489"},
        }
    ]

    assert smoke._database_url_password(
        "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/nex_ae_test"
    ) == "sensitive-pass"
    assert smoke._database_url_password(None) is None
    assert smoke._database_url_password("postgresql://user@127.0.0.1/db") is None
    assert smoke._database_url_password("http://[::1") is None
    assert smoke._metadata_only({"safe": "ok"}, forbidden_fragments=["secret"])
    assert not smoke._metadata_only(
        {"leak": "storage_ref"},
        forbidden_fragments=["storage_ref"],
    )
    assert smoke._worker_dry_run_execution(worker_result)
    assert not smoke._worker_dry_run_execution({"execution": None})
    assert not smoke._worker_dry_run_execution(
        {
            "execution": {
                **worker_result["execution"],
                "storage_mutation_enabled": True,
            }
        }
    )
    assert smoke._history_row_matches_worker(history_rows, worker_result)
    assert not smoke._history_row_matches_worker([], worker_result)
    assert "secret-0489" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="NEX_AE_ARTIFACT_STORAGE_ROOT"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=secret-0489", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/ae/artifacts", {})

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduled_execution_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_artifact_retention_scheduled_execution_postgres_smoke=skipped"
        in capsys.readouterr().out
    )
