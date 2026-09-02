from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke as smoke
from run_migrations import MigrationError
from test_ae_artifact_retention_scheduler_tick_once_postgres_smoke import (
    good_observations,
)
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0536@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def test_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke_skips() -> (
    None
):
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke({})
    )

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_retention_scheduler_daemon_one_cycle_rejects_dev_profile() -> (
    None
):
    evidence = smoke.run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_retention_scheduler_daemon_one_cycle_missing_db_url() -> None:
    evidence = smoke.run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_retention_scheduler_daemon_one_cycle_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0536")
        ),
    )

    evidence = smoke.run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0536" not in evidence["detail"]


def test_ae_artifact_retention_scheduler_daemon_one_cycle_passes_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("0513_ae_artifact_retention_scheduler_lease",),
            applied=(),
            skipped=("0513_ae_artifact_retention_scheduler_lease",),
        ),
    )

    evidence = smoke.run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke(
        smoke_env()
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["one_cycle"] == {
        "schema_version": (
            smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_SCHEMA_VERSION
        ),
        "result_status": "SUCCEEDED",
        "skip_reason": None,
        "loop_decision_status": "READY",
        "loop_decision_reason": None,
        "tick_once_ran": True,
        "job_enqueued": True,
        "lease_released": True,
    }
    assert evidence["runtime_config"] == {
        "enablement_status": "READY",
        "explicit_opt_in": True,
        "continuous_loop_started": False,
    }
    assert evidence["daemon_config"]["lease_backend"] == "sqlalchemy"
    assert evidence["daemon_config"]["scheduler_daemon_started"] is False
    assert evidence["tick_once"]["result_status"] == "SUCCEEDED"
    assert evidence["tick_once"]["lease_acquired"] is True
    assert evidence["tick_once"]["lease_released"] is True
    assert evidence["tick_once"]["job_enqueued"] is True
    assert evidence["tick_once"]["worker_executed"] is True
    assert evidence["history"]["row_count"] == 1
    assert evidence["history"]["mode"] == "DRY_RUN"
    assert evidence["history"]["execution_status"] == "SUCCEEDED"
    assert evidence["lease"]["lease_status"] == "RELEASED"
    assert evidence["job"]["status"] == "SUCCEEDED"
    assert evidence["db_before"] == good_observations()
    assert evidence["db_after_worker"] == good_observations()
    assert evidence["materialized_file_count"] == {"before": 6, "after_worker": 6}
    assert all(evidence["checks"].values())
    assert evidence["cleanup"] == {
        "artifacts": 3,
        "handoffs": 3,
        "history_rows": 1,
        "job_rows": 1,
        "heartbeat_rows": 0,
        "lease_rows": 1,
    }
    assert evidence["live_db"] is True
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke=pass "
        "service=nex-ae-api"
    )
    assert "secret-0536" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "storage_ref" not in serialized


def test_ae_artifact_retention_scheduler_daemon_one_cycle_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke.candidate_pg, "_count_files", lambda _root: 0)

    with pytest.raises(RuntimeError, match="storage_files_retained"):
        smoke._execute_ae_artifact_retention_scheduler_daemon_one_cycle_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduler_daemon_one_cycle_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_retention_scheduler_daemon_one_cycle_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = smoke.run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_artifact_retention_scheduler_daemon_one_cycle_helpers() -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert smoke._database_url_password(
        "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/nex_ae_test"
    ) == "sensitive-pass"
    assert smoke._database_url_password(None) is None
    assert smoke._database_url_password("postgresql://user@127.0.0.1/db") is None
    assert smoke._database_url_password("http://[::1") is None
    assert "secret-0536" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    with pytest.raises(ValueError, match="raw NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("secret-0536", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/private", {})


def test_ae_artifact_retention_scheduler_daemon_one_cycle_main_outputs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    skipped = {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    failure = {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": "nex-ae-api",
        "failure_code": "execution_failed",
    }
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke",
        lambda: skipped,
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke=skipped"
        in capsys.readouterr().out
    )
    assert smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke",
        lambda: failure,
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=execution_failed" in capsys.readouterr().out
