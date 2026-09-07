from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0578@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def _passing_migration() -> SimpleNamespace:
    return SimpleNamespace(
        planned=(smoke.process_pg.MIGRATION_VERSION,),
        applied=(),
        skipped=(smoke.process_pg.MIGRATION_VERSION,),
    )


def _passing_observations() -> dict[str, Any]:
    return {
        "dialect": "sqlite",
        "tables_present": sorted(smoke.process_pg.EXPECTED_TABLES),
        "indexes_present": sorted(smoke.process_pg.EXPECTED_INDEXES),
        "migration_recorded": True,
        "row_counts": {"process_records": 2, "process_events": 2},
        "record_counts": {
            "status_probe_missing": 1,
            "start_daemon_running": 1,
            "running_pid": 1,
        },
        "jsonb_columns": {},
    }


def test_ae_ag_daemon_supervised_process_read_model_postgres_smoke_skips() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke(
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
        "ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_ag_daemon_supervised_process_read_model_rejects_non_test_profile() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke(
            {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke="
        "fail service=nex-ae-api ag_service=nex-ag reason=profile_not_allowed"
    )


def test_ae_ag_daemon_supervised_process_read_model_requires_database_url() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_ag_daemon_supervised_process_read_model_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0578")
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0578" not in evidence["detail"]


def test_ae_ag_daemon_supervised_process_read_model_passes_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke(
            smoke_env()
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    summary = smoke.summary_line(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["migration"] == {
        "planned": [smoke.process_pg.MIGRATION_VERSION],
        "applied": [],
        "skipped": [smoke.process_pg.MIGRATION_VERSION],
    }
    assert evidence["dispatches"]["status_probe_missing"]["process_status"] == (
        "MISSING"
    )
    assert evidence["dispatches"]["start_daemon_running"]["process_status"] == (
        "RUNNING"
    )
    assert evidence["dispatches"]["start_daemon_running"]["process_id"] == (
        smoke.RUNNING_PROCESS_ID
    )
    assert evidence["routes"] == {
        "ae_process_collection_statuses": [200],
        "ae_process_detail_statuses": [200],
        "ag_process_collection_status": 200,
        "ag_process_detail_status": 200,
    }
    assert evidence["db_observations"]["row_counts"] == {
        "process_records": 2,
        "process_events": 2,
    }
    assert evidence["ag_process_collection"]["projection_schema_version"] == (
        smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert evidence["ag_process_collection"]["projection_status"] == "READY"
    assert evidence["ag_process_collection"]["count"] == 1
    assert evidence["ag_process_collection"]["filter"]["process_status"] == "RUNNING"
    assert evidence["ag_process_collection"]["summary"]["running_count"] == 1
    assert evidence["ag_process_collection"]["source_status"]["source_kind"] == (
        "ae_test_client"
    )
    assert evidence["ag_process_collection"]["operator_guidance"][
        "ag_direct_database_write_allowed"
    ] is False
    assert evidence["ag_process_detail"]["projection_schema_version"] == (
        smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert evidence["ag_process_detail"]["projection_status"] == "READY"
    assert evidence["ag_process_detail"]["supervised_process_event_count"] == 1
    assert evidence["ag_process_detail"]["summary"]["process_status"] == "RUNNING"
    assert evidence["ag_process_detail"]["summary"]["process_running"] is True
    assert evidence["ag_process_detail"]["source_status"][
        "process_snapshot_detail_loaded"
    ] is True
    assert all(evidence["checks"].values())
    assert evidence["cleanup"] == {
        "daemon_supervised_process_events": 2,
        "daemon_supervised_process_records": 2,
    }
    assert evidence["post_cleanup"]["row_counts"] == {
        "process_records": 0,
        "process_events": 0,
    }
    assert evidence["live_db"] is True
    assert summary.startswith(
        "ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke="
        "pass service=nex-ae-api ag_service=nex-ag"
    )
    assert "db_records=2" in summary
    assert "secret-0578" not in serialized
    assert "/data/nex-platform" not in serialized


def test_ae_ag_daemon_supervised_process_read_model_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke.process_pg,
        "_db_observations",
        lambda *args, **kwargs: {
            **_passing_observations(),
            "row_counts": {"process_records": 0, "process_events": 0},
        },
    )

    with pytest.raises(RuntimeError, match="process_rows_persisted"):
        smoke._execute_ae_ag_daemon_supervised_process_read_model_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_daemon_supervised_process_read_model_cleanup_verification_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    observations = iter(
        [
            _passing_observations(),
            {
                **_passing_observations(),
                "row_counts": {"process_records": 1, "process_events": 1},
            },
        ]
    )
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke.process_pg,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="cleanup verification"):
        smoke._execute_ae_ag_daemon_supervised_process_read_model_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_daemon_supervised_process_read_model_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_ag_daemon_supervised_process_read_model_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_ag_daemon_supervised_process_bridge_and_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __init__(self, status_code: int, payload: Any = None) -> None:
            self.status_code = status_code
            self._payload = payload or {}
            self.content = b"{}"

        def json(self) -> Any:
            return self._payload

    class FakeClient:
        def __init__(self, responses: list[FakeResponse]) -> None:
            self.responses = responses
            self.calls: list[dict[str, Any]] = []

        def get(
            self,
            url: str,
            *,
            params: dict[str, str] | None = None,
            headers: dict[str, str],
        ) -> FakeResponse:
            self.calls.append({"url": url, "params": params or {}, "headers": headers})
            return self.responses.pop(0)

    bridge = smoke.AeTestClientDaemonSupervisedProcessReadModelClient(
        FakeClient([FakeResponse(200, {"count": 0}), FakeResponse(404, {})]),
        headers={"Authorization": "Bearer token"},
    )
    collection = bridge.list_artifact_retention_scheduler_daemon_process_snapshots(
        scheduler_id="scheduler-0578",
        action="start_daemon",
        process_status="RUNNING",
        limit=5,
        request_id="request-0578",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    missing = bridge.get_artifact_retention_scheduler_daemon_process_snapshot_detail(
        "missing",
        request_id="request-0578",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert collection == {"count": 0}
    assert missing is None
    assert bridge.process_collection_statuses == [200]
    assert bridge.process_detail_statuses == [404]
    assert bridge.client.calls[0]["params"] == {
        "limit": "5",
        "scheduler_id": "scheduler-0578",
        "action": "start_daemon",
        "process_status": "RUNNING",
    }
    assert smoke._scheduler_id_from_dispatches({}, {}) == (
        "ae-artifact-retention-scheduler-local-v1"
    )
    assert smoke._mapping_value({"ok": True}) == {"ok": True}
    assert smoke._mapping_value([]) == {}
    assert smoke._metadata_only({"safe": "ok"}, forbidden_fragments=["secret"])
    assert not smoke._metadata_only(
        {"leak": "content_base64"},
        forbidden_fragments=["content_base64"],
    )

    failing_bridge = smoke.AeTestClientDaemonSupervisedProcessReadModelClient(
        FakeClient(
            [
                FakeResponse(
                    503,
                    {
                        "error_code": "ae.process_down",
                        "detail": "source down",
                    },
                )
            ]
        ),
        headers={},
    )
    with pytest.raises(smoke.AeArtifactOperationsError) as source_error:
        failing_bridge.list_artifact_retention_scheduler_daemon_process_snapshots(
            scheduler_id=None,
            action=None,
            process_status=None,
            limit=20,
            request_id="request-0578",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )
    assert source_error.value.error_code == "ae.process_down"

    monkeypatch.setattr(smoke.process_pg, "_safe_detail", lambda detail, env: detail)
    assert "dev" not in smoke._safe_detail(
        "profile dev is not allowed",
        {smoke.SMOKE_PROFILE_ENV: "dev"},
    )
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("secret-0578", smoke_env())


def test_ae_ag_daemon_supervised_process_read_model_main_outputs(
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
        "ag_service_id": "nex-ag",
        "failure_code": "execution_failed",
    }
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke",
        lambda: skipped,
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke="
        "skipped"
    ) in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke",
        lambda: failure,
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=execution_failed" in capsys.readouterr().out
