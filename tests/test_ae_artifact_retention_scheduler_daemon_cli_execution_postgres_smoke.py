from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke as smoke
from run_migrations import MigrationError
from test_ae_artifact_retention_scheduler_tick_once_postgres_smoke import (
    good_observations,
)
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0556@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def test_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke_skips() -> (
    None
):
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke(
            {}
        )
    )

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_retention_scheduler_daemon_cli_execution_rejects_dev_profile() -> (
    None
):
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke(
            {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_retention_scheduler_daemon_cli_execution_missing_db_url() -> None:
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_retention_scheduler_daemon_cli_execution_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0556")
        ),
    )

    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0556" not in evidence["detail"]


def test_ae_artifact_retention_scheduler_daemon_cli_execution_passes_sqlite_harness(
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

    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke(
            smoke_env()
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["cli_execution"] == {
        "schema_version": (
            smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_RESULT_SCHEMA_VERSION
        ),
        "result_status": "SUCCEEDED",
        "stop_reason": "max_cycles_reached",
        "max_cycles": 2,
        "cycle_count": 2,
        "completed_run_status": "SUCCEEDED",
        "bounded_loop_started": True,
        "job_enqueued": True,
        "worker_executed": True,
        "run_record_persisted": False,
        "summary_line": (
            "ae_scheduler_daemon_cli_execution=pass "
            f"scheduler_id={evidence['daemon_config']['scheduler_id']} "
            "result=SUCCEEDED stop_reason=max_cycles_reached max_cycles=2 "
            "cycles=2 job_enqueued=1 persisted=0"
        ),
    }
    assert evidence["bounded_loop"]["result_status"] == "SUCCEEDED"
    assert evidence["bounded_loop"]["cycle_count"] == 2
    assert evidence["bounded_loop"]["worker_executed"] is True
    assert [item["cycle_index"] for item in evidence["cycles"]] == [1, 2]
    assert [item["requested_at"] for item in evidence["cycles"]] == [
        smoke.TICK_AT,
        smoke.SECOND_TICK_AT,
    ]
    assert all(item["result_status"] == "SUCCEEDED" for item in evidence["cycles"])
    assert evidence["runtime_config"] == {
        "enablement_status": "READY",
        "explicit_opt_in": True,
        "continuous_loop_started": False,
    }
    assert evidence["daemon_config"]["lease_backend"] == "sqlalchemy"
    assert evidence["lease"]["lease_status"] == "RELEASED"
    assert evidence["lease"]["fencing_token"] == 2
    assert evidence["jobs"]["row_count"] == 2
    assert evidence["jobs"]["statuses"] == ["SUCCEEDED", "SUCCEEDED"]
    assert evidence["jobs"]["attempt_counts"] == [1, 1]
    assert evidence["history"] == {
        "row_count": 2,
        "modes": ["DRY_RUN", "DRY_RUN"],
        "execution_statuses": ["SUCCEEDED", "SUCCEEDED"],
    }
    assert evidence["daemon_heartbeat"]["stored"] == {
        "row_found": True,
        "status": "IDLE",
        "active_job_id": None,
        "metadata_phase": "one_cycle_finished",
        "loop_decision_status": "READY",
    }
    assert evidence["daemon_runtime"]["heartbeat_status"] == "IDLE"
    assert evidence["db_before"] == good_observations()
    assert evidence["db_after_worker"] == good_observations()
    assert evidence["materialized_file_count"] == {"before": 6, "after_worker": 6}
    assert all(evidence["checks"].values())
    assert evidence["cleanup"] == {
        "artifacts": 3,
        "handoffs": 3,
        "history_rows": 2,
        "job_rows": 2,
        "worker_heartbeat_rows": 0,
        "daemon_heartbeat_rows": 1,
        "lease_rows": 1,
    }
    assert evidence["live_db"] is True
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke=pass "
        "service=nex-ae-api"
    )
    assert "cycles=2" in smoke.summary_line(evidence)
    assert "secret-0556" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "storage_ref" not in serialized


def test_ae_artifact_retention_scheduler_daemon_cli_execution_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke.candidate_pg, "_count_files", lambda _root: 0)

    with pytest.raises(RuntimeError, match="storage_files_retained"):
        smoke._execute_ae_artifact_retention_scheduler_daemon_cli_execution_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduler_daemon_cli_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_retention_scheduler_daemon_cli_execution_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_artifact_retention_scheduler_daemon_cli_execution_helpers() -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    with pytest.raises(ValueError, match="raw NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("secret-0556", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/private", {})


def test_ae_artifact_retention_scheduler_daemon_cli_execution_main_outputs(
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
        "run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke",
        lambda: skipped,
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke=skipped"
        in capsys.readouterr().out
    )
    assert smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke",
        lambda: failure,
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=execution_failed" in capsys.readouterr().out
