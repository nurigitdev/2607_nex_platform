from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_retention_scheduler_tick_once_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0515@127.0.0.1:5432/"
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


def test_ae_artifact_retention_scheduler_tick_once_postgres_smoke_skips() -> None:
    evidence = smoke.run_ae_artifact_retention_scheduler_tick_once_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_tick_once_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_retention_scheduler_tick_once_postgres_smoke_rejects_dev_profile() -> None:
    evidence = smoke.run_ae_artifact_retention_scheduler_tick_once_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_tick_once_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_retention_scheduler_tick_once_postgres_smoke_missing_db_url() -> None:
    evidence = smoke.run_ae_artifact_retention_scheduler_tick_once_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_retention_scheduler_tick_once_postgres_smoke_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad secret-0515")),
    )

    evidence = smoke.run_ae_artifact_retention_scheduler_tick_once_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0515" not in evidence["detail"]


def test_ae_artifact_retention_scheduler_tick_once_postgres_smoke_passes_sqlite_harness(
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

    evidence = smoke.run_ae_artifact_retention_scheduler_tick_once_postgres_smoke(
        smoke_env()
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["tick_once"]["schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION
    )
    assert evidence["tick_once"]["result_status"] == "SUCCEEDED"
    assert evidence["tick_once"]["skip_reason"] is None
    assert evidence["tick_once"]["lease_acquired"] is True
    assert evidence["tick_once"]["lease_released"] is True
    assert evidence["tick_once"]["job_enqueued"] is True
    assert evidence["tick_once"]["worker_executed"] is True
    assert evidence["tick_once"]["history_write_executed"] is True
    assert evidence["batch_plan"] == {
        "plan_status": "READY",
        "scheduler_status": "DISABLED",
        "candidate_count": 2,
        "selected_count": 1,
        "selected_artifact_ids": evidence["batch_plan"]["selected_artifact_ids"],
    }
    assert evidence["scheduler_tick"]["tick_status"] == "READY"
    assert evidence["scheduler_tick"]["enqueue_status"] == "ENQUEUED"
    assert evidence["lease"]["row_count"] == 1
    assert evidence["lease"]["lease_status"] == "RELEASED"
    assert evidence["lease"]["fencing_token"] == 1
    assert evidence["job"]["status"] == "SUCCEEDED"
    assert evidence["job"]["attempt_count"] == 1
    assert evidence["job"]["payload_command_status"] == "READY"
    assert evidence["worker"]["runner_status"] == "SUCCEEDED"
    assert evidence["history"]["row_count"] == 1
    assert evidence["history"]["mode"] == "DRY_RUN"
    assert evidence["history"]["execution_status"] == "SUCCEEDED"
    assert evidence["db_before"] == good_observations()
    assert evidence["db_after_worker"] == good_observations()
    assert evidence["materialized_file_count"] == {
        "before": 6,
        "after_worker": 6,
    }
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
        "ae_artifact_retention_scheduler_tick_once_postgres_smoke=pass "
        "service=nex-ae-api"
    )
    assert "secret-0515" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "storage_ref" not in serialized


def test_ae_artifact_retention_scheduler_tick_once_postgres_smoke_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke.candidate_pg, "_count_files", lambda _root: 0)

    with pytest.raises(RuntimeError, match="storage_files_retained"):
        smoke._execute_ae_artifact_retention_scheduler_tick_once_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduler_tick_once_postgres_smoke_value_error(
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
        smoke._execute_ae_artifact_retention_scheduler_tick_once_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduler_tick_once_postgres_smoke_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_retention_scheduler_tick_once_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = smoke.run_ae_artifact_retention_scheduler_tick_once_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_artifact_retention_scheduler_tick_once_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert smoke._database_url_password(
        "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/nex_ae_test"
    ) == "sensitive-pass"
    assert smoke._database_url_password(None) is None
    assert smoke._database_url_password("postgresql://user@127.0.0.1/db") is None
    assert smoke._database_url_password("http://[::1") is None
    assert smoke._metadata_only({"safe": "ok"}, forbidden_fragments=["secret"])
    assert not smoke._metadata_only(
        {"leak": "content_base64"},
        forbidden_fragments=["content_base64"],
    )
    assert smoke._mapping_value({"ok": True}) == {"ok": True}
    assert smoke._mapping_value([]) == {}
    assert smoke._json_value(None, {"default": True}) == {"default": True}
    assert smoke._json_value('{"ok": true}', {}) == {"ok": True}
    assert smoke._json_value({"ok": True}, {}) == {"ok": True}
    smoke._ensure_sqlite_scheduler_lease_table(
        SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    assert smoke._cleanup_scheduler_once_lease_rows(
        engine,
        scheduler_id="missing",
        lease_owner_id="missing",
    ) == 0
    smoke._ensure_sqlite_scheduler_lease_table(engine)
    assert smoke._scheduler_once_lease_observation(
        engine,
        scheduler_id="missing",
        lease_owner_id="missing",
    )["row_count"] == 0
    checks = smoke._scheduler_tick_once_checks(
        database_url=env["NEX_AE_TEST_DATABASE_URL"],
        database_env="NEX_AE_TEST_DATABASE_URL",
        storage_root=__import__("pathlib").Path("/tmp/safe-storage"),
        scheduler_config_response=503,
        scheduler_config={},
        tick_once_result={},
        lease_observation={},
        job_observation={},
        history_rows=[],
        before={"artifact_rows": 1},
        after={"artifact_rows": 0},
        materialized_before=0,
        materialized_after=1,
    )
    assert not all(checks.values())
    assert "secret-0515" not in checks
    assert smoke._history_execution_id({}) is None
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="NEX_AE_ARTIFACT_STORAGE_ROOT"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=secret-0515", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/ae/artifacts", {})

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_tick_once_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_artifact_retention_scheduler_tick_once_postgres_smoke=skipped"
        in capsys.readouterr().out
    )
    quality_gate = (smoke.ROOT / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    assert "run_ae_artifact_retention_scheduler_tick_once_postgres_smoke.py" in quality_gate
