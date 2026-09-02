from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke as smoke
from run_migrations import MigrationError
from test_ae_artifact_retention_scheduler_tick_once_postgres_smoke import (
    good_observations,
)
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0526@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke_skips() -> None:
    evidence = smoke.run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_daemon_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke_rejects_dev_profile() -> (
    None
):
    evidence = smoke.run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_daemon_postgres_smoke=fail "
        "service=nex-ae-api ag_service=nex-ag reason=profile_not_allowed"
    )


def test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke_missing_db_url() -> (
    None
):
    evidence = smoke.run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0526")
        ),
    )

    evidence = smoke.run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0526" not in evidence["detail"]


def test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke_passes_sqlite_harness(
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

    evidence = smoke.run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke(
        smoke_env()
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["routes"] == {
        "ag_daemon_config_status": 200,
        "ag_manual_tick_once_status": 200,
        "ae_daemon_config_statuses": [200, 200],
        "ae_daemon_control_statuses": [200],
    }
    assert evidence["ag_daemon_config"] == {
        "projection_schema_version": (
            smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "READY",
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "manual_tick_once_available": True,
        "start_daemon_available": False,
        "source_kind": "ae_test_client",
    }
    assert evidence["ag_manual_tick"] == {
        "projection_schema_version": (
            smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "READY",
        "dispatch_status": "DISPATCHED",
        "dispatch_action": "manual_tick_once",
        "job_enqueued": True,
        "tick_once_dispatched": True,
        "tick_once_result_status": "SUCCEEDED",
    }
    assert evidence["ae_raw_dispatch"] == {
        "schema_version": (
            smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION
        ),
        "dispatch_status": "DISPATCHED",
        "control_status": "READY",
        "tick_once_present": True,
        "tick_once_result_status": "SUCCEEDED",
    }
    assert evidence["lease"]["lease_status"] == "RELEASED"
    assert evidence["job"]["job_type"] == smoke.AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE
    assert evidence["job"]["status"] == "SUCCEEDED"
    assert evidence["job"]["attempt_count"] == 1
    assert evidence["job"]["payload_command_status"] == "READY"
    assert evidence["history"]["row_count"] == 1
    assert evidence["history"]["mode"] == "DRY_RUN"
    assert evidence["history"]["execution_status"] == "SUCCEEDED"
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
        "ae_ag_artifact_retention_scheduler_daemon_postgres_smoke=pass "
        "service=nex-ae-api ag_service=nex-ag"
    )
    assert "secret-0526" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "storage_ref" not in serialized


def test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke.candidate_pg, "_count_files", lambda _root: 0)

    with pytest.raises(RuntimeError, match="storage_files_retained"):
        smoke._execute_ae_ag_artifact_retention_scheduler_daemon_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke_wraps_value_error(
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
        smoke._execute_ae_ag_artifact_retention_scheduler_daemon_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_ag_artifact_retention_scheduler_daemon_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = smoke.run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_ag_artifact_retention_scheduler_daemon_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert smoke._ag_auth_headers(
        request_id="request-0526",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )["Authorization"].startswith("Bearer ")
    assert (
        smoke._database_url_password(
            "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/nex_ae_test"
        )
        == "sensitive-pass"
    )
    assert smoke._database_url_password(None) is None
    assert smoke._database_url_password("postgresql://user@127.0.0.1/db") is None
    assert smoke._database_url_password("http://[::1") is None
    assert smoke._mapping_value({"ok": True}) == {"ok": True}
    assert smoke._mapping_value([]) == {}
    assert smoke._metadata_only({"safe": "ok"}, forbidden_fragments=["secret"])
    assert not smoke._metadata_only(
        {"leak": "content_base64"},
        forbidden_fragments=["content_base64"],
    )
    assert "secret-0526" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    checks = smoke._ag_scheduler_daemon_checks(
        database_url=env["NEX_AE_TEST_DATABASE_URL"],
        database_env="NEX_AE_TEST_DATABASE_URL",
        storage_root=Path("/tmp/safe-storage"),
        config_response=503,
        config_projection={},
        manual_response=503,
        manual_projection={},
        bridge=SimpleNamespace(daemon_config_statuses=[], daemon_control_statuses=[]),
        raw_dispatch={},
        raw_tick_once={},
        lease_observation={},
        job_observation={},
        history_rows=[],
        before={"artifact_rows": 1},
        after={"artifact_rows": 0},
        materialized_before=0,
        materialized_after=1,
    )
    assert not all(checks.values())
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="NEX_AE_ARTIFACT_STORAGE_ROOT"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=secret-0526", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/ae/artifacts", {})

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_ag_artifact_retention_scheduler_daemon_postgres_smoke=skipped"
        in capsys.readouterr().out
    )
