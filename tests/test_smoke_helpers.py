from __future__ import annotations

import io
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from sqlalchemy import text

import run_ag_job_control_smoke as ag_job_control_smoke
import run_ag_operations_dashboard_smoke as ag_operations_dashboard_smoke
import run_ag_cross_service_observability_smoke as ag_observability_smoke
import run_ag_cx_processing_run_postgres_smoke as ag_cx_processing_smoke
import run_ag_retrieval_package_postgres_smoke as ag_retrieval_postgres_smoke
import run_ag_service_log_retention_smoke as ag_log_retention_smoke
import run_ag_service_log_retention_postgres_smoke as ag_log_retention_postgres_smoke
import check_backend_service_endpoints as endpoint_smoke
import check_db_readiness as db_smoke
import run_cx_processing_postgres_event_smoke as cx_processing_event_smoke
import run_cx_processing_postgres_jobqueue_smoke as cx_processing_smoke
import run_cx_processing_postgres_persistence_smoke as cx_processing_persistence_smoke
import run_cx_processing_postgres_api_smoke as cx_processing_api_smoke
import run_cx_upload_ownership_postgres_smoke as cx_upload_ownership_smoke
import run_cx_upload_duplicate_postgres_smoke as cx_upload_duplicate_smoke
import run_cx_document_library_postgres_smoke as cx_document_library_smoke
import run_cx_retrieval_postgres_smoke as cx_retrieval_smoke
import run_postgres_job_replay_smoke as job_replay_smoke
import run_postgres_jobqueue_smoke as jobqueue_smoke
import run_postgres_operational_event_smoke as event_smoke
import run_postgres_operations_smoke_pack as operations_smoke
import run_postgres_service_log_retention_http_smoke as service_log_retention_http_smoke
import run_postgres_service_log_smoke as service_log_smoke
import run_postgres_service_log_retention_smoke as service_log_retention_smoke
import run_postgres_test_smoke_suite as postgres_suite_smoke


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeDbCursor:
    def __enter__(self) -> "FakeDbCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.sql = sql

    def fetchone(self) -> tuple[str, str]:
        return ("nex_example_dev", "nex_example_user")


class FakeDbConnection:
    def __enter__(self) -> "FakeDbConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> FakeDbCursor:
        return FakeDbCursor()


class FakeSqlConnection:
    def __enter__(self) -> "FakeSqlConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: object, params: dict[str, object]) -> None:
        self.sql = sql
        self.params = params


class FakeSqlEngine:
    def begin(self) -> FakeSqlConnection:
        return FakeSqlConnection()


class FakeRetentionServiceLogStore:
    def __init__(self, session_factory: object) -> None:
        self.session_factory = session_factory
        self.entries: dict[str, dict[str, object]] = {}
        self.retention_history: dict[str, dict[str, object]] = {}

    def append(self, entry: dict[str, object]) -> dict[str, object]:
        self.entries[str(entry["log_id"])] = dict(entry)
        return dict(entry)

    def get_log(self, log_id: str) -> dict[str, object] | None:
        entry = self.entries.get(log_id)
        return dict(entry) if entry is not None else None

    def purge_retention_candidates(
        self,
        *,
        service_id: str,
        retention_cutoff: str,
        retention_days: int = 30,
        checked_at: str | None = None,
        dry_run: bool = True,
        delete_enabled: bool = False,
        max_delete_count: int = 100,
        requested_by: dict[str, object] | None = None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, object]:
        candidates = [
            entry
            for entry in self.entries.values()
            if entry["service_id"] == service_id
            and str(entry["observed_at"]) < retention_cutoff
        ]
        candidates.sort(
            key=lambda entry: (str(entry["observed_at"]), str(entry["log_id"]))
        )
        if dry_run:
            mode = "DRY_RUN"
            status = "SUCCEEDED"
            deleted = 0
            blocked_reason = None
        elif not delete_enabled:
            mode = "EXECUTE"
            status = "BLOCKED"
            deleted = 0
            blocked_reason = "delete_not_enabled"
        else:
            mode = "EXECUTE"
            status = "SUCCEEDED"
            selected = candidates[:max_delete_count]
            for entry in selected:
                self.entries.pop(str(entry["log_id"]), None)
            deleted = len(selected)
            blocked_reason = None
        result = {
            "retention_execution_schema_version": (
                "service_log_retention_execution.v1"
            ),
            "execution_id": f"fake-{idempotency_key}",
            "service_id": service_id,
            "mode": mode,
            "execution_status": status,
            "retention_days": retention_days,
            "retention_cutoff": retention_cutoff,
            "checked_at": checked_at,
            "max_delete_count": max_delete_count,
            "candidate_count": len(candidates),
            "deleted_count": deleted,
            "delete_enabled": delete_enabled,
            "requested_by": requested_by,
            "idempotency_key": idempotency_key,
            "trace_id": trace_id,
            "request_id": request_id,
            "blocked_reason": blocked_reason,
        }
        self.record_retention_history(result, recorded_at=checked_at)
        return result

    def record_retention_history(
        self,
        execution: dict[str, object],
        *,
        recorded_at: str | None = None,
    ) -> dict[str, object]:
        entry = {
            "retention_history_schema_version": (
                "service_log_retention_history_entry.v1"
            ),
            "execution_id": execution["execution_id"],
            "service_id": execution["service_id"],
            "mode": execution["mode"],
            "execution_status": execution["execution_status"],
            "delete_enabled": execution["delete_enabled"],
            "retention_days": execution["retention_days"],
            "retention_cutoff": execution["retention_cutoff"],
            "checked_at": execution["checked_at"],
            "recorded_at": recorded_at or execution["checked_at"],
            "candidate_count": execution["candidate_count"],
            "deleted_count": execution["deleted_count"],
            "requested_by": execution["requested_by"],
            "idempotency_key": execution["idempotency_key"],
            "trace_id": execution["trace_id"],
            "request_id": execution["request_id"],
            "blocked_reason": execution["blocked_reason"],
            "error": None,
            "execution": dict(execution),
        }
        self.retention_history[str(entry["execution_id"])] = entry
        return dict(entry)

    def get_retention_history(self, execution_id: str) -> dict[str, object] | None:
        entry = self.retention_history.get(execution_id)
        return dict(entry) if entry is not None else None

    def list_retention_history(
        self,
        *,
        service_id: str | None = None,
        mode: str | None = None,
        execution_status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        entries = []
        for entry in self.retention_history.values():
            if service_id is not None and entry["service_id"] != service_id:
                continue
            if mode is not None and entry["mode"] != mode:
                continue
            if execution_status is not None and entry["execution_status"] != execution_status:
                continue
            if trace_id is not None and entry["trace_id"] != trace_id:
                continue
            if request_id is not None and entry["request_id"] != request_id:
                continue
            if idempotency_key is not None and entry["idempotency_key"] != idempotency_key:
                continue
            entries.append(dict(entry))
        entries.sort(
            key=lambda entry: (str(entry["recorded_at"]), str(entry["execution_id"])),
            reverse=True,
        )
        return entries[:limit]


@pytest.mark.parametrize(
    ("payload", "summary"),
    [
        ({"health_status": "HEALTHY"}, "health_status=HEALTHY"),
        ({"readiness_status": "READY"}, "readiness_status=READY"),
        ({"version": "0.0.0"}, "version=0.0.0"),
        ({"other": "value"}, "response=received"),
    ],
)
def test_endpoint_summary(payload: dict[str, object], summary: str) -> None:
    assert endpoint_smoke._summarize(payload) == summary


def test_fetch_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        endpoint_smoke,
        "urlopen",
        lambda url, timeout: FakeHttpResponse({"version": "1.2.3"}),
    )

    ok, summary = endpoint_smoke._fetch("http://example.test/version")

    assert ok is True
    assert summary == "version=1.2.3"


def test_fetch_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_http_error(url: str, timeout: int) -> None:
        raise HTTPError(url, 503, "unavailable", hdrs=None, fp=io.BytesIO())

    monkeypatch.setattr(endpoint_smoke, "urlopen", raise_http_error)

    ok, summary = endpoint_smoke._fetch("http://example.test/ready")

    assert ok is False
    assert summary == "http_status=503"


def test_fetch_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_url_error(url: str, timeout: int) -> None:
        raise URLError("connection refused")

    monkeypatch.setattr(endpoint_smoke, "urlopen", raise_url_error)

    ok, summary = endpoint_smoke._fetch("http://example.test/ready")

    assert ok is False
    assert summary == "URLError"


def test_endpoint_main_returns_zero_when_all_checks_pass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(endpoint_smoke, "SERVICES", {"nex-test": 8999})
    monkeypatch.setattr(endpoint_smoke, "_fetch", lambda url: (True, "ok"))

    assert endpoint_smoke.main() == 0
    assert "nex-test /health: OK ok" in capsys.readouterr().out


def test_endpoint_main_returns_failure_when_any_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(endpoint_smoke, "SERVICES", {"nex-test": 8999})
    monkeypatch.setattr(endpoint_smoke, "_fetch", lambda url: (False, "boom"))

    assert endpoint_smoke.main() == 1


def test_ag_operations_dashboard_smoke_passes_mock_pack() -> None:
    evidence = ag_operations_dashboard_smoke.run_ag_operations_dashboard_smoke()

    assert evidence["status"] == "PASS"
    assert evidence["endpoint_count"] == 20
    assert all(evidence["checks"].values())
    assert evidence["counts"] == {
        "sources": 1,
        "events": 1,
        "logs": 1,
        "retention_history": 1,
        "jobs": 2,
        "cx_processing_runs": 2,
        "cx_processing_run_steps": 2,
        "workers": 1,
        "worker_detail_events": 1,
        "trace_timeline": 5,
        "rollups": 1,
        "dashboard_degraded_sources": 0,
        "dashboard_replay_candidates": 1,
        "issue_candidates": 3,
    }
    assert ag_operations_dashboard_smoke.summary_line(evidence) == (
        "ag_operations_dashboard_smoke=pass endpoints=20 jobs=2 workers=1 "
        "processing_runs=2 events=1 logs=1 history=1 issues=3"
    )
    assert "private" not in json.dumps(evidence, ensure_ascii=False)


def test_ag_operations_dashboard_smoke_reports_failed_summary() -> None:
    assert ag_operations_dashboard_smoke.summary_line(
        {"status": "FAIL", "counts": {}}
    ) == "ag_operations_dashboard_smoke=fail"


def test_ag_operations_dashboard_smoke_main_prints_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ag_operations_dashboard_smoke.main(["--summary"]) == 0
    assert "ag_operations_dashboard_smoke=pass" in capsys.readouterr().out


def test_ag_job_control_smoke_passes_mock_pack() -> None:
    evidence = ag_job_control_smoke.run_ag_job_control_smoke()

    assert evidence["status"] == "PASS"
    assert evidence["actions"] == ["cancel", "retry", "replay"]
    assert evidence["projection_versions"] == {
        "cancel": "ag_job_control_dispatch.v1",
        "retry": "ag_job_control_dispatch.v1",
        "replay": "ag_job_control_dispatch.v1",
        "service_response": "service_job_control.v1",
    }
    assert evidence["job_statuses"] == {
        "cancel": "CANCELLED",
        "retry": "QUEUED",
        "replay_source": "FAILED",
        "replay": "QUEUED",
    }
    assert evidence["audit_event_count"] == 3
    assert all(evidence["checks"].values())
    assert "source_file_id" not in json.dumps(evidence, ensure_ascii=False)
    assert ag_job_control_smoke.summary_line(evidence) == (
        "ag_job_control_smoke=pass actions=3 audit_events=3 "
        "cancel_status=CANCELLED retry_status=QUEUED replay_status=QUEUED"
    )


def test_ag_job_control_smoke_reports_failed_summary() -> None:
    assert ag_job_control_smoke.summary_line({"status": "FAIL"}) == "ag_job_control_smoke=fail"


def test_ag_job_control_smoke_local_client_maps_service_errors() -> None:
    queue = ag_job_control_smoke.InMemoryJobQueue()
    queue.enqueue(
        ag_job_control_smoke._sample_job(
            job_id="queued",
            idempotency_key="queued-idem",
        )
    )
    service_client = ag_job_control_smoke._build_cx_service_client(queue)
    control_client = ag_job_control_smoke.LocalAgJobControlClient({"nex-cx": service_client})

    with pytest.raises(ag_job_control_smoke.AgJobControlError) as invalid_retry:
        control_client.retry_job(
            "nex-cx",
            "queued",
            request_id=ag_job_control_smoke.REQUEST_ID,
            trace_id=ag_job_control_smoke.TRACE_ID,
        )
    with pytest.raises(ag_job_control_smoke.AgJobControlError) as invalid_replay:
        control_client.replay_job(
            "nex-cx",
            "queued",
            request_id=ag_job_control_smoke.REQUEST_ID,
            trace_id=ag_job_control_smoke.TRACE_ID,
            replay_job_id="queued-replay",
            idempotency_key="queued-replay-idem",
            requested_by="operator-smoke",
            reason="not dead-lettered",
        )
    with pytest.raises(ag_job_control_smoke.AgJobControlError) as missing_service:
        control_client.get_job(
            "nex-mo",
            "queued",
            request_id=ag_job_control_smoke.REQUEST_ID,
            trace_id=ag_job_control_smoke.TRACE_ID,
        )

    assert invalid_retry.value.status_code == 409
    assert invalid_retry.value.error_code == "job.retry_status_invalid"
    assert invalid_replay.value.status_code == 409
    assert invalid_replay.value.error_code == "job_replay.status_invalid"
    assert missing_service.value.status_code == 404
    assert missing_service.value.error_code == "ag.job_control_service_not_configured"


def test_ag_job_control_smoke_main_prints_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ag_job_control_smoke.main(["--summary"]) == 0
    assert "ag_job_control_smoke=pass" in capsys.readouterr().out


def test_ag_service_log_retention_smoke_passes_mock_pack() -> None:
    evidence = ag_log_retention_smoke.run_ag_service_log_retention_smoke()

    assert evidence["status"] == "PASS"
    assert evidence["actions"] == ["dry_run", "blocked", "execute"]
    assert evidence["projection_versions"] == {
        "dry_run": "ag_service_log_retention_dispatch.v1",
        "execute": "ag_service_log_retention_dispatch.v1",
        "service_response": "service_log_retention_execution.v1",
    }
    assert evidence["http_statuses"] == {
        "dry_run": 200,
        "blocked": 409,
        "execute": 200,
    }
    assert evidence["counts"] == {
        "candidate_count": 2,
        "deleted_count": 1,
        "audit_events": 3,
        "service_calls": 2,
    }
    assert all(evidence["checks"].values())
    assert "Bearer private" not in json.dumps(evidence, ensure_ascii=False)
    assert ag_log_retention_smoke.summary_line(evidence) == (
        "ag_service_log_retention_smoke=pass actions=3 audit_events=3 "
        "dry_run_status=200 blocked_status=409 execute_deleted=1"
    )


def test_ag_service_log_retention_smoke_reports_failed_summary() -> None:
    assert ag_log_retention_smoke.summary_line({"status": "FAIL"}) == (
        "ag_service_log_retention_smoke=fail"
    )


def test_ag_service_log_retention_smoke_local_client_maps_service_errors() -> None:
    service_client = ag_log_retention_smoke._build_cx_service_client(
        ag_log_retention_smoke._build_cx_log_store()
    )
    control_client = ag_log_retention_smoke.LocalAgServiceLogRetentionClient(
        {"nex-cx": service_client}
    )

    with pytest.raises(ag_log_retention_smoke.AgServiceLogRetentionError) as bad_payload:
        control_client.purge_logs(
            "nex-cx",
            request_id=ag_log_retention_smoke.REQUEST_ID,
            trace_id=ag_log_retention_smoke.TRACE_ID,
            retention_cutoff="2026-07-06T00:00:00Z",
            dry_run=True,
            delete_enabled=True,
        )
    with pytest.raises(ag_log_retention_smoke.AgServiceLogRetentionError) as missing:
        control_client.purge_logs(
            "nex-mo",
            request_id=ag_log_retention_smoke.REQUEST_ID,
            trace_id=ag_log_retention_smoke.TRACE_ID,
            retention_cutoff="2026-07-06T00:00:00Z",
        )

    assert bad_payload.value.status_code == 422
    assert bad_payload.value.error_code == "service_log_retention.delete_enabled_invalid"
    assert missing.value.status_code == 404
    assert missing.value.error_code == (
        "ag.service_log_retention_service_not_configured"
    )


def test_ag_service_log_retention_smoke_main_prints_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ag_log_retention_smoke.main(["--summary"]) == 0
    assert "ag_service_log_retention_smoke=pass" in capsys.readouterr().out


def test_ag_service_log_retention_smoke_main_prints_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ag_log_retention_smoke.main([]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["smoke_schema_version"] == "ag_service_log_retention_smoke.v1"
    assert payload["status"] == "PASS"


def test_ag_service_log_retention_smoke_main_returns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ag_log_retention_smoke,
        "run_ag_service_log_retention_smoke",
        lambda: {"status": "FAIL", "counts": {}},
    )

    assert ag_log_retention_smoke.main(["--summary"]) == 1


def test_ag_service_log_retention_smoke_module_entrypoint(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["run_ag_service_log_retention_smoke.py"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(Path(ag_log_retention_smoke.__file__).resolve()),
            run_name="__main__",
        )

    assert exc_info.value.code == 0
    assert "ag_service_log_retention_smoke.v1" in capsys.readouterr().out


def test_ag_service_log_retention_postgres_smoke_skips_by_default() -> None:
    evidence = ag_log_retention_postgres_smoke.run_ag_service_log_retention_postgres_smoke(
        environ={}
    )

    assert evidence["status"] == "SKIPPED"
    assert ag_log_retention_postgres_smoke.summary_line(evidence) == (
        "ag_service_log_retention_postgres_smoke=skipped "
        "reason=NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE"
    )


def test_ag_service_log_retention_postgres_smoke_rejects_bad_profile_and_service() -> None:
    bad_profile = (
        ag_log_retention_postgres_smoke.run_ag_service_log_retention_postgres_smoke(
            environ={
                "NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE": "1",
                "NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE_PROFILE": "dev",
            }
        )
    )
    bad_service = (
        ag_log_retention_postgres_smoke.run_ag_service_log_retention_postgres_smoke(
            environ={
                "NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE": "1",
                "NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE_SERVICE": "unknown",
            }
        )
    )

    assert bad_profile["failure_code"] == "profile_not_allowed"
    assert bad_service["failure_code"] == "service_invalid"


def test_ag_service_log_retention_postgres_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append(
            (service_id, profile)
        ),
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "database_pool_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "build_engine",
        lambda *args, **kwargs: FakeSqlEngine(),
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "build_session_factory",
        lambda engine: object(),
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "SqlAlchemyServiceLogStore",
        FakeRetentionServiceLogStore,
    )

    evidence = ag_log_retention_postgres_smoke.run_ag_service_log_retention_postgres_smoke(
        environ={
            "NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE": "1",
            "NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE_SERVICE": "nex-cx",
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["http_statuses"] == {
        "dry_run": 200,
        "blocked": 409,
        "execute": 200,
        "history": 200,
    }
    assert evidence["projection_versions"] == {
        "dry_run": "ag_service_log_retention_dispatch.v1",
        "execute": "ag_service_log_retention_dispatch.v1",
        "service_response": "service_log_retention_execution.v1",
        "history": "ag_service_log_retention_history_projection.v1",
    }
    assert evidence["counts"] == {
        "candidate_count": 2,
        "deleted_count": 1,
        "history_count": 2,
        "history_deleted_count": 1,
        "audit_events": 3,
        "service_calls": 2,
        "remaining_old_count": 1,
        "remaining_fresh_count": 1,
    }
    assert all(evidence["checks"].values())
    assert "secret" not in str(evidence)
    assert "Bearer private" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert ag_log_retention_postgres_smoke.summary_line(evidence) == (
        "ag_service_log_retention_postgres_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env "
        "audit_events=3 service_calls=2 deleted=1 history=2"
    )


def test_ag_service_log_retention_postgres_smoke_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenRetentionServiceLogStore(FakeRetentionServiceLogStore):
        def purge_retention_candidates(self, **kwargs: object) -> dict[str, object]:
            result = super().purge_retention_candidates(**kwargs)
            result["candidate_count"] = 0
            return result

    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "service_database_env",
        lambda *args, **kwargs: "NEX_CX_TEST_DATABASE_URL",
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "database_pool_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "build_engine",
        lambda *args, **kwargs: FakeSqlEngine(),
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "build_session_factory",
        lambda engine: object(),
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "SqlAlchemyServiceLogStore",
        BrokenRetentionServiceLogStore,
    )

    checks_failure = (
        ag_log_retention_postgres_smoke.run_ag_service_log_retention_postgres_smoke(
            environ={"NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE": "1"}
        )
    )

    assert checks_failure["status"] == "FAIL"
    assert checks_failure["failure_code"] == "checks_failed"
    assert checks_failure["database_env"] == "NEX_CX_TEST_DATABASE_URL"

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise ag_log_retention_postgres_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = (
        ag_log_retention_postgres_smoke.run_ag_service_log_retention_postgres_smoke(
            environ={"NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE": "1"}
        )
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "build_engine",
        raise_runtime_error,
    )
    execution_failure = (
        ag_log_retention_postgres_smoke.run_ag_service_log_retention_postgres_smoke(
            environ={"NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE": "1"}
        )
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert ag_log_retention_postgres_smoke.summary_line(execution_failure) == (
        "ag_service_log_retention_postgres_smoke=fail "
        "service=nex-cx reason=execution_failed"
    )


def test_ag_service_log_retention_postgres_smoke_helpers_cover_edges() -> None:
    assert (
        ag_log_retention_postgres_smoke._redaction_safe(
            {"redacted_database_url": "postgresql://user:secret@localhost/db"}
        )
        is False
    )
    checks = ag_log_retention_postgres_smoke._checks(
        dry_run={
            "_http_status": 200,
            "projection_schema_version": "ag_service_log_retention_dispatch.v1",
            "summary": {"candidate_count": 1, "deleted_count": 0},
            "service_response": {
                "retention_execution_schema_version": (
                    "service_log_retention_execution.v1"
                )
            },
        },
        blocked={
            "_http_status": 409,
            "error_code": "ag.service_log_retention_delete_not_enabled",
        },
        execute={
            "_http_status": 200,
            "summary": {"candidate_count": 2, "deleted_count": 1},
            "service_response": {
                "retention_execution_schema_version": (
                    "service_log_retention_execution.v1"
                ),
                "service_id": "nex-cx",
            },
        },
        history={
            "_http_status": 200,
            "projection_schema_version": (
                "ag_service_log_retention_history_projection.v1"
            ),
            "projection_status": "READY",
            "source_statuses": {"nex-cx": {"status": "READY"}},
            "summary": {
                "total": 2,
                "by_mode": {"DRY_RUN": 1, "EXECUTE": 1},
                "by_status": {"SUCCEEDED": 2},
                "deleted_count": 1,
            },
        },
        state={
            "old_001_remaining": False,
            "old_002_remaining": True,
            "fresh_remaining": True,
        },
        audit_events=[
            {"event_type": ag_log_retention_postgres_smoke.AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED},
            {"event_type": ag_log_retention_postgres_smoke.AG_SERVICE_LOG_RETENTION_EVENT_FAILED},
            {"event_type": ag_log_retention_postgres_smoke.AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED},
        ],
        calls_after_dry_run=1,
        calls_after_blocked=1,
        service_call_count=2,
    )

    assert checks["dry_run_dispatch_reached_postgres_service"] is False


def test_ag_service_log_retention_postgres_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "load_env_file",
        lambda path: None,
    )
    monkeypatch.setattr(
        ag_log_retention_postgres_smoke,
        "run_ag_service_log_retention_postgres_smoke",
        lambda: {
            "smoke_schema_version": "ag_service_log_retention_postgres_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": (
                "NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE is not enabled."
            ),
        },
    )

    assert ag_log_retention_postgres_smoke.main(["--summary"]) == 0
    assert "ag_service_log_retention_postgres_smoke=skipped" in capsys.readouterr().out

    assert ag_log_retention_postgres_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_db_smoke_reports_missing_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(db_smoke, "DATABASE_ENVS", {"nex-test": "NEX_TEST_DATABASE_URL"})
    monkeypatch.delenv("NEX_TEST_DATABASE_URL", raising=False)

    assert db_smoke.main() == 1
    assert "missing NEX_TEST_DATABASE_URL" in capsys.readouterr().out


def test_db_smoke_reports_connection_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(db_smoke, "DATABASE_ENVS", {"nex-test": "NEX_TEST_DATABASE_URL"})
    monkeypatch.setenv("NEX_TEST_DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(
        db_smoke,
        "check_database_readiness",
        lambda env_name, environ: {
            "name": "database",
            "ok": True,
            "database_env": env_name,
            "database_name": "nex_example_dev",
            "database_user": "nex_example_user",
            "latency_ms": 1,
        },
    )

    assert db_smoke.main() == 0
    output = capsys.readouterr().out
    assert "nex-test: READY" in output
    assert "db=nex_example_dev" in output


def test_db_smoke_reports_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(db_smoke, "DATABASE_ENVS", {"nex-test": "NEX_TEST_DATABASE_URL"})
    monkeypatch.setenv("NEX_TEST_DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(
        db_smoke,
        "check_database_readiness",
        lambda env_name, environ: {
            "name": "database",
            "ok": False,
            "database_env": env_name,
            "error_code": "DATABASE_CONNECTION_FAILED",
            "latency_ms": 1,
        },
    )

    assert db_smoke.main() == 1
    assert "connection failed" in capsys.readouterr().out


def test_db_smoke_reports_placeholder_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(db_smoke, "DATABASE_ENVS", {"nex-test": "NEX_TEST_DATABASE_URL"})
    monkeypatch.setattr(
        db_smoke,
        "check_database_readiness",
        lambda env_name, environ: {
            "name": "database",
            "ok": False,
            "database_env": env_name,
            "error_code": "DATABASE_URL_PLACEHOLDER",
            "latency_ms": 0,
        },
    )

    assert db_smoke.main() == 1
    assert "placeholder NEX_TEST_DATABASE_URL" in capsys.readouterr().out


def test_postgres_jobqueue_smoke_skips_by_default() -> None:
    evidence = jobqueue_smoke.run_postgres_jobqueue_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert jobqueue_smoke.summary_line(evidence) == (
        "postgres_jobqueue_smoke=skipped reason=NEX_DB_JOBQUEUE_SMOKE"
    )


def test_postgres_jobqueue_smoke_rejects_non_test_profile() -> None:
    evidence = jobqueue_smoke.run_postgres_jobqueue_smoke(
        environ={
            "NEX_DB_JOBQUEUE_SMOKE": "1",
            "NEX_DB_JOBQUEUE_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_postgres_jobqueue_smoke_reports_pass_without_leaking_database_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    class FakeJobQueue:
        def __init__(self, session_factory: object) -> None:
            self.session_factory = session_factory
            self.job: dict[str, object] | None = None

        def enqueue(self, job: dict[str, object]) -> dict[str, object]:
            if self.job is None:
                self.job = dict(job)
            return dict(self.job)

        def claim_next_job(self, worker_id: str, *, updated_at: str) -> dict[str, object]:
            assert worker_id == "postgres-smoke-worker"
            assert self.job is not None
            return {**self.job, "status": "RUNNING", "attempt_count": 1}

        def complete_job(self, job_id: str, *, updated_at: str) -> dict[str, object]:
            assert self.job is not None
            return {**self.job, "job_id": job_id, "status": "SUCCEEDED"}

    monkeypatch.setattr(
        jobqueue_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        jobqueue_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        jobqueue_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append((service_id, profile)),
    )
    monkeypatch.setattr(jobqueue_smoke, "database_pool_settings", lambda *args, **kwargs: object())
    monkeypatch.setattr(jobqueue_smoke, "build_engine", lambda *args, **kwargs: FakeSqlEngine())
    monkeypatch.setattr(jobqueue_smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(jobqueue_smoke, "SqlAlchemyJobQueue", FakeJobQueue)

    evidence = jobqueue_smoke.run_postgres_jobqueue_smoke(
        environ={
            "NEX_DB_JOBQUEUE_SMOKE": "1",
            "NEX_DB_JOBQUEUE_SMOKE_SERVICE": "nex-cx",
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "enqueue": True,
        "idempotency": True,
        "claim": True,
        "complete": True,
    }
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert jobqueue_smoke.summary_line(evidence) == (
        "postgres_jobqueue_smoke=pass service=nex-cx db_env=nex-cx:test:env"
    )


def test_postgres_jobqueue_smoke_reports_claim_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingClaimQueue:
        def __init__(self, session_factory: object) -> None:
            self.session_factory = session_factory

        def enqueue(self, job: dict[str, object]) -> dict[str, object]:
            return dict(job)

        def claim_next_job(self, worker_id: str, *, updated_at: str) -> None:
            return None

    monkeypatch.setattr(jobqueue_smoke, "service_database_env", lambda *args, **kwargs: "NEX_CX_TEST_DATABASE_URL")
    monkeypatch.setattr(
        jobqueue_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(jobqueue_smoke, "run_service_migrations", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobqueue_smoke, "database_pool_settings", lambda *args, **kwargs: object())
    monkeypatch.setattr(jobqueue_smoke, "build_engine", lambda *args, **kwargs: FakeSqlEngine())
    monkeypatch.setattr(jobqueue_smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(jobqueue_smoke, "SqlAlchemyJobQueue", MissingClaimQueue)

    evidence = jobqueue_smoke.run_postgres_jobqueue_smoke(
        environ={"NEX_DB_JOBQUEUE_SMOKE": "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "claim_missing"
    assert evidence["database_env"] == "NEX_CX_TEST_DATABASE_URL"


def test_postgres_jobqueue_smoke_reports_configuration_and_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobqueue_smoke,
        "service_database_env",
        lambda *args, **kwargs: "NEX_CX_TEST_DATABASE_URL",
    )

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise jobqueue_smoke.MigrationError("missing database URL env NEX_CX_TEST_DATABASE_URL")

    monkeypatch.setattr(jobqueue_smoke, "service_database_url", raise_migration_error)
    config_failure = jobqueue_smoke.run_postgres_jobqueue_smoke(
        environ={"NEX_DB_JOBQUEUE_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        jobqueue_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(jobqueue_smoke, "run_service_migrations", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobqueue_smoke, "database_pool_settings", lambda *args, **kwargs: object())

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(jobqueue_smoke, "build_engine", raise_runtime_error)
    execution_failure = jobqueue_smoke.run_postgres_jobqueue_smoke(
        environ={"NEX_DB_JOBQUEUE_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert jobqueue_smoke.summary_line(execution_failure) == (
        "postgres_jobqueue_smoke=fail service=nex-cx reason=execution_failed"
    )


def test_postgres_jobqueue_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(jobqueue_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        jobqueue_smoke,
        "run_postgres_jobqueue_smoke",
        lambda: {
            "smoke_schema_version": "postgres_jobqueue_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_DB_JOBQUEUE_SMOKE is not enabled.",
        },
    )

    assert jobqueue_smoke.main(["--summary"]) == 0
    assert "postgres_jobqueue_smoke=skipped" in capsys.readouterr().out

    assert jobqueue_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_postgres_job_replay_smoke_skips_by_default() -> None:
    evidence = job_replay_smoke.run_postgres_job_replay_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert job_replay_smoke.summary_line(evidence) == (
        "postgres_job_replay_smoke=skipped reason=NEX_DB_JOB_REPLAY_SMOKE"
    )


def test_postgres_job_replay_smoke_rejects_non_test_profile() -> None:
    evidence = job_replay_smoke.run_postgres_job_replay_smoke(
        environ={
            "NEX_DB_JOB_REPLAY_SMOKE": "1",
            "NEX_DB_JOB_REPLAY_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_postgres_job_replay_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    class FakeReplayQueue:
        def __init__(self, session_factory: object) -> None:
            self.session_factory = session_factory
            self.jobs: dict[str, dict[str, object]] = {}
            self.idempotency: dict[tuple[str, str], str] = {}

        def enqueue(self, job: dict[str, object]) -> dict[str, object]:
            key = (str(job["job_type"]), str(job["idempotency_key"]))
            existing_id = self.idempotency.get(key)
            if existing_id is not None:
                return dict(self.jobs[existing_id])
            stored = dict(job)
            self.jobs[str(stored["job_id"])] = stored
            self.idempotency[key] = str(stored["job_id"])
            return dict(stored)

        def claim_next_job(
            self,
            worker_id: str,
            *,
            job_type: str,
            updated_at: str,
        ) -> dict[str, object]:
            assert worker_id == "postgres-replay-smoke-worker"
            source = next(job for job in self.jobs.values() if job["job_type"] == job_type)
            source.update({"status": "RUNNING", "attempt_count": 1, "updated_at": updated_at})
            return dict(source)

        def retry_job(
            self,
            job_id: str,
            *,
            error: dict[str, object],
            failed_at: str,
        ) -> dict[str, object]:
            source = self.jobs[job_id]
            source.update(
                {
                    "status": "FAILED",
                    "retryable": False,
                    "updated_at": failed_at,
                    "available_at": failed_at,
                    "error": {
                        **error,
                        "failed_at": failed_at,
                        "dead_lettered": True,
                        "retryable": False,
                    },
                }
            )
            return dict(source)

        def get_job(self, job_id: str) -> dict[str, object] | None:
            job = self.jobs.get(job_id)
            return dict(job) if job is not None else None

    monkeypatch.setattr(
        job_replay_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        job_replay_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        job_replay_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append((service_id, profile)),
    )
    monkeypatch.setattr(job_replay_smoke, "database_pool_settings", lambda *args, **kwargs: object())
    monkeypatch.setattr(job_replay_smoke, "build_engine", lambda *args, **kwargs: FakeSqlEngine())
    monkeypatch.setattr(job_replay_smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(job_replay_smoke, "SqlAlchemyJobQueue", FakeReplayQueue)

    evidence = job_replay_smoke.run_postgres_job_replay_smoke(
        environ={
            "NEX_DB_JOB_REPLAY_SMOKE": "1",
            "NEX_DB_JOB_REPLAY_SMOKE_SERVICE": "nex-cx",
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "source_enqueued": True,
        "source_claimed": True,
        "source_dead_lettered": True,
        "replay_enqueued": True,
        "payload_copied": True,
        "lineage_persisted": True,
        "idempotency": True,
        "readback": True,
    }
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert job_replay_smoke.summary_line(evidence) == (
        "postgres_job_replay_smoke=pass service=nex-cx db_env=nex-cx:test:env"
    )


def test_postgres_job_replay_smoke_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        job_replay_smoke,
        "service_database_env",
        lambda *args, **kwargs: "NEX_CX_TEST_DATABASE_URL",
    )

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise job_replay_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(job_replay_smoke, "service_database_url", raise_migration_error)
    config_failure = job_replay_smoke.run_postgres_job_replay_smoke(
        environ={"NEX_DB_JOB_REPLAY_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        job_replay_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(job_replay_smoke, "run_service_migrations", lambda *args, **kwargs: None)
    monkeypatch.setattr(job_replay_smoke, "database_pool_settings", lambda *args, **kwargs: object())

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(job_replay_smoke, "build_engine", raise_runtime_error)
    execution_failure = job_replay_smoke.run_postgres_job_replay_smoke(
        environ={"NEX_DB_JOB_REPLAY_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert job_replay_smoke.summary_line(execution_failure) == (
        "postgres_job_replay_smoke=fail service=nex-cx reason=execution_failed"
    )


def test_postgres_job_replay_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(job_replay_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        job_replay_smoke,
        "run_postgres_job_replay_smoke",
        lambda: {
            "smoke_schema_version": "postgres_job_replay_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_DB_JOB_REPLAY_SMOKE is not enabled.",
        },
    )

    assert job_replay_smoke.main(["--summary"]) == 0
    assert "postgres_job_replay_smoke=skipped" in capsys.readouterr().out

    assert job_replay_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_postgres_operational_event_smoke_skips_by_default() -> None:
    evidence = event_smoke.run_postgres_operational_event_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert event_smoke.summary_line(evidence) == (
        "postgres_operational_event_smoke=skipped reason=NEX_DB_OPERATIONAL_EVENT_SMOKE"
    )


def test_postgres_operational_event_smoke_rejects_non_test_profile() -> None:
    evidence = event_smoke.run_postgres_operational_event_smoke(
        environ={
            "NEX_DB_OPERATIONAL_EVENT_SMOKE": "1",
            "NEX_DB_OPERATIONAL_EVENT_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_postgres_operational_event_smoke_reports_pass_without_leaking_database_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    class FakeOperationalEventStore:
        def __init__(self, session_factory: object) -> None:
            self.session_factory = session_factory
            self.event: dict[str, object] | None = None

        def append(self, event: dict[str, object]) -> dict[str, object]:
            if self.event is None:
                self.event = dict(event)
            return dict(self.event)

        def list_events(self, **filters: object) -> list[dict[str, object]]:
            assert filters["severity"] == "warning"
            assert self.event is not None
            return [dict(self.event)]

        def summary(self) -> dict[str, object]:
            assert self.event is not None
            return {"by_service": {self.event["service_id"]: 1}}

    monkeypatch.setattr(
        event_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        event_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        event_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append((service_id, profile)),
    )
    monkeypatch.setattr(event_smoke, "database_pool_settings", lambda *args, **kwargs: object())
    monkeypatch.setattr(event_smoke, "build_engine", lambda *args, **kwargs: FakeSqlEngine())
    monkeypatch.setattr(event_smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(event_smoke, "SqlAlchemyOperationalEventStore", FakeOperationalEventStore)

    evidence = event_smoke.run_postgres_operational_event_smoke(
        environ={
            "NEX_DB_OPERATIONAL_EVENT_SMOKE": "1",
            "NEX_DB_OPERATIONAL_EVENT_SMOKE_SERVICE": "nex-cx",
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "append": True,
        "idempotency": True,
        "redaction": True,
        "list_filter": True,
        "summary": True,
    }
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert "must be redacted" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert event_smoke.summary_line(evidence) == (
        "postgres_operational_event_smoke=pass service=nex-cx db_env=nex-cx:test:env"
    )


def test_postgres_operational_event_smoke_reports_configuration_and_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_failure = event_smoke._failure(
        "direct_failure",
        "boom",
        service_id="nex-cx",
        profile="test",
        database_env="NEX_CX_TEST_DATABASE_URL",
    )
    assert direct_failure["database_env"] == "NEX_CX_TEST_DATABASE_URL"

    monkeypatch.setattr(
        event_smoke,
        "service_database_env",
        lambda *args, **kwargs: "NEX_CX_TEST_DATABASE_URL",
    )

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise event_smoke.MigrationError("missing database URL env NEX_CX_TEST_DATABASE_URL")

    monkeypatch.setattr(event_smoke, "service_database_url", raise_migration_error)
    config_failure = event_smoke.run_postgres_operational_event_smoke(
        environ={"NEX_DB_OPERATIONAL_EVENT_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        event_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(event_smoke, "run_service_migrations", lambda *args, **kwargs: None)
    monkeypatch.setattr(event_smoke, "database_pool_settings", lambda *args, **kwargs: object())

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(event_smoke, "build_engine", raise_runtime_error)
    execution_failure = event_smoke.run_postgres_operational_event_smoke(
        environ={"NEX_DB_OPERATIONAL_EVENT_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert event_smoke.summary_line(execution_failure) == (
        "postgres_operational_event_smoke=fail service=nex-cx reason=execution_failed"
    )


def test_postgres_operational_event_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(event_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        event_smoke,
        "run_postgres_operational_event_smoke",
        lambda: {
            "smoke_schema_version": "postgres_operational_event_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_DB_OPERATIONAL_EVENT_SMOKE is not enabled.",
        },
    )

    assert event_smoke.main(["--summary"]) == 0
    assert "postgres_operational_event_smoke=skipped" in capsys.readouterr().out

    assert event_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_postgres_service_log_smoke_skips_by_default() -> None:
    evidence = service_log_smoke.run_postgres_service_log_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert service_log_smoke.summary_line(evidence) == (
        "postgres_service_log_smoke=skipped reason=NEX_DB_SERVICE_LOG_SMOKE"
    )


def test_postgres_service_log_smoke_rejects_non_test_profile() -> None:
    evidence = service_log_smoke.run_postgres_service_log_smoke(
        environ={
            "NEX_DB_SERVICE_LOG_SMOKE": "1",
            "NEX_DB_SERVICE_LOG_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_postgres_service_log_smoke_reports_pass_without_leaking_database_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    class FakeServiceLogStore:
        def __init__(self, session_factory: object) -> None:
            self.session_factory = session_factory
            self.log: dict[str, object] | None = None

        def append(self, entry: dict[str, object]) -> dict[str, object]:
            if self.log is None:
                self.log = dict(entry)
            return dict(self.log)

        def get_log(self, log_id: str) -> dict[str, object] | None:
            assert self.log is not None
            assert self.log["log_id"] == log_id
            return dict(self.log)

        def list_logs(self, **filters: object) -> list[dict[str, object]]:
            assert filters["severity"] == "error"
            assert filters["logger_name"] == service_log_smoke.LOGGER_NAME
            assert self.log is not None
            return [dict(self.log)]

        def summary(self) -> dict[str, object]:
            assert self.log is not None
            return {
                "by_service": {self.log["service_id"]: 1},
                "by_severity": {"ERROR": 1},
            }

    monkeypatch.setattr(
        service_log_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        service_log_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        service_log_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append(
            (service_id, profile)
        ),
    )
    monkeypatch.setattr(
        service_log_smoke,
        "database_pool_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(service_log_smoke, "build_engine", lambda *args, **kwargs: FakeSqlEngine())
    monkeypatch.setattr(service_log_smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(service_log_smoke, "SqlAlchemyServiceLogStore", FakeServiceLogStore)

    evidence = service_log_smoke.run_postgres_service_log_smoke(
        environ={
            "NEX_DB_SERVICE_LOG_SMOKE": "1",
            "NEX_DB_SERVICE_LOG_SMOKE_SERVICE": "nex-cx",
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "append": True,
        "idempotency": True,
        "readback": True,
        "jsonb_redaction": True,
        "redaction": True,
        "list_filter": True,
        "summary": True,
    }
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert "Bearer private" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert service_log_smoke.summary_line(evidence) == (
        "postgres_service_log_smoke=pass service=nex-cx db_env=nex-cx:test:env"
    )


def test_postgres_service_log_smoke_reports_check_configuration_and_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingReadbackServiceLogStore:
        def __init__(self, session_factory: object) -> None:
            self.session_factory = session_factory

        def append(self, entry: dict[str, object]) -> dict[str, object]:
            return dict(entry)

        def get_log(self, log_id: str) -> None:
            return None

        def list_logs(self, **filters: object) -> list[dict[str, object]]:
            return []

        def summary(self) -> dict[str, object]:
            return {"by_service": {}, "by_severity": {}}

    monkeypatch.setattr(
        service_log_smoke,
        "service_database_env",
        lambda *args, **kwargs: "NEX_CX_TEST_DATABASE_URL",
    )
    monkeypatch.setattr(
        service_log_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(service_log_smoke, "run_service_migrations", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service_log_smoke,
        "database_pool_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(service_log_smoke, "build_engine", lambda *args, **kwargs: FakeSqlEngine())
    monkeypatch.setattr(service_log_smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        service_log_smoke,
        "SqlAlchemyServiceLogStore",
        MissingReadbackServiceLogStore,
    )

    checks_failure = service_log_smoke.run_postgres_service_log_smoke(
        environ={"NEX_DB_SERVICE_LOG_SMOKE": "1"}
    )

    assert checks_failure["status"] == "FAIL"
    assert checks_failure["failure_code"] == "checks_failed"
    assert checks_failure["database_env"] == "NEX_CX_TEST_DATABASE_URL"

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise service_log_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(service_log_smoke, "service_database_url", raise_migration_error)
    config_failure = service_log_smoke.run_postgres_service_log_smoke(
        environ={"NEX_DB_SERVICE_LOG_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        service_log_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(service_log_smoke, "build_engine", raise_runtime_error)
    execution_failure = service_log_smoke.run_postgres_service_log_smoke(
        environ={"NEX_DB_SERVICE_LOG_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert service_log_smoke.summary_line(execution_failure) == (
        "postgres_service_log_smoke=fail service=nex-cx reason=execution_failed"
    )


def test_postgres_service_log_smoke_helpers_cover_redaction_edges() -> None:
    assert service_log_smoke._jsonb_redaction_check(None) is False
    assert service_log_smoke._jsonb_redaction_check({"attributes": []}) is False
    assert (
        service_log_smoke._jsonb_redaction_check(
            {"attributes": {"nested": []}, "redacted_attribute_keys": []}
        )
        is False
    )
    assert (
        service_log_smoke._redaction_safe(
            {"attributes": {"nested": {"api_key": "secret-token-value"}}}
        )
        is False
    )


def test_postgres_service_log_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(service_log_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        service_log_smoke,
        "run_postgres_service_log_smoke",
        lambda: {
            "smoke_schema_version": "postgres_service_log_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_DB_SERVICE_LOG_SMOKE is not enabled.",
        },
    )

    assert service_log_smoke.main(["--summary"]) == 0
    assert "postgres_service_log_smoke=skipped" in capsys.readouterr().out

    assert service_log_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_postgres_service_log_retention_smoke_skips_by_default() -> None:
    evidence = service_log_retention_smoke.run_postgres_service_log_retention_smoke(
        environ={}
    )

    assert evidence["status"] == "SKIPPED"
    assert service_log_retention_smoke.summary_line(evidence) == (
        "postgres_service_log_retention_smoke=skipped "
        "reason=NEX_DB_SERVICE_LOG_RETENTION_SMOKE"
    )


def test_postgres_service_log_retention_smoke_rejects_non_test_profile() -> None:
    evidence = service_log_retention_smoke.run_postgres_service_log_retention_smoke(
        environ={
            "NEX_DB_SERVICE_LOG_RETENTION_SMOKE": "1",
            "NEX_DB_SERVICE_LOG_RETENTION_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_postgres_service_log_retention_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        service_log_retention_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append(
            (service_id, profile)
        ),
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "database_pool_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "build_engine",
        lambda *args, **kwargs: FakeSqlEngine(),
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "build_session_factory",
        lambda engine: object(),
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "SqlAlchemyServiceLogStore",
        FakeRetentionServiceLogStore,
    )

    evidence = service_log_retention_smoke.run_postgres_service_log_retention_smoke(
        environ={
            "NEX_DB_SERVICE_LOG_RETENTION_SMOKE": "1",
            "NEX_DB_SERVICE_LOG_RETENTION_SMOKE_SERVICE": "nex-cx",
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "dry_run_succeeded_without_delete": True,
        "execute_without_delete_enabled_blocked": True,
        "execute_deleted_one_candidate": True,
        "store_state_guarded": True,
        "retention_window_fixed": True,
    }
    assert evidence["counts"] == {
        "dry_run_candidate_count": 2,
        "blocked_candidate_count": 2,
        "execute_candidate_count": 2,
        "execute_deleted_count": 1,
        "remaining_old_count": 1,
        "remaining_fresh_count": 1,
    }
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert "Bearer private" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert service_log_retention_smoke.summary_line(evidence) == (
        "postgres_service_log_retention_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env deleted=1"
    )


def test_postgres_service_log_retention_smoke_reports_check_configuration_and_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenRetentionServiceLogStore(FakeRetentionServiceLogStore):
        def purge_retention_candidates(self, **kwargs: object) -> dict[str, object]:
            result = super().purge_retention_candidates(**kwargs)
            result["candidate_count"] = 0
            return result

    monkeypatch.setattr(
        service_log_retention_smoke,
        "service_database_env",
        lambda *args, **kwargs: "NEX_CX_TEST_DATABASE_URL",
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "database_pool_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "build_engine",
        lambda *args, **kwargs: FakeSqlEngine(),
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "build_session_factory",
        lambda engine: object(),
    )
    monkeypatch.setattr(
        service_log_retention_smoke,
        "SqlAlchemyServiceLogStore",
        BrokenRetentionServiceLogStore,
    )

    checks_failure = (
        service_log_retention_smoke.run_postgres_service_log_retention_smoke(
            environ={"NEX_DB_SERVICE_LOG_RETENTION_SMOKE": "1"}
        )
    )

    assert checks_failure["status"] == "FAIL"
    assert checks_failure["failure_code"] == "checks_failed"
    assert checks_failure["database_env"] == "NEX_CX_TEST_DATABASE_URL"

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise service_log_retention_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        service_log_retention_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = (
        service_log_retention_smoke.run_postgres_service_log_retention_smoke(
            environ={"NEX_DB_SERVICE_LOG_RETENTION_SMOKE": "1"}
        )
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        service_log_retention_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(service_log_retention_smoke, "build_engine", raise_runtime_error)
    execution_failure = (
        service_log_retention_smoke.run_postgres_service_log_retention_smoke(
            environ={"NEX_DB_SERVICE_LOG_RETENTION_SMOKE": "1"}
        )
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert service_log_retention_smoke.summary_line(execution_failure) == (
        "postgres_service_log_retention_smoke=fail "
        "service=nex-cx reason=execution_failed"
    )


def test_postgres_service_log_retention_smoke_helpers_cover_edges() -> None:
    assert (
        service_log_retention_smoke._redaction_safe(
            {"redacted_database_url": "postgresql://user:secret@localhost/db"}
        )
        is False
    )
    assert service_log_retention_smoke._checks(
        dry_run={
            "retention_execution_schema_version": (
                "service_log_retention_execution.v1"
            ),
            "mode": "DRY_RUN",
            "execution_status": "SUCCEEDED",
            "candidate_count": 1,
            "deleted_count": 0,
            "delete_enabled": False,
            "retention_cutoff": service_log_retention_smoke.RETENTION_CUTOFF,
        },
        blocked={
            "mode": "EXECUTE",
            "execution_status": "BLOCKED",
            "candidate_count": 2,
            "deleted_count": 0,
            "blocked_reason": "delete_not_enabled",
        },
        execute={
            "mode": "EXECUTE",
            "execution_status": "SUCCEEDED",
            "candidate_count": 2,
            "deleted_count": 1,
            "delete_enabled": True,
            "max_delete_count": service_log_retention_smoke.MAX_DELETE_COUNT,
            "checked_at": service_log_retention_smoke.CHECKED_AT,
        },
        state={
            "old_001_remaining": False,
            "old_002_remaining": True,
            "fresh_remaining": True,
        },
    )["dry_run_succeeded_without_delete"] is False


def test_postgres_service_log_retention_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(service_log_retention_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        service_log_retention_smoke,
        "run_postgres_service_log_retention_smoke",
        lambda: {
            "smoke_schema_version": "postgres_service_log_retention_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_DB_SERVICE_LOG_RETENTION_SMOKE is not enabled.",
        },
    )

    assert service_log_retention_smoke.main(["--summary"]) == 0
    assert "postgres_service_log_retention_smoke=skipped" in capsys.readouterr().out

    assert service_log_retention_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_postgres_service_log_retention_http_smoke_skips_by_default() -> None:
    evidence = service_log_retention_http_smoke.run_postgres_service_log_retention_http_smoke(
        environ={}
    )

    assert evidence["status"] == "SKIPPED"
    assert service_log_retention_http_smoke.summary_line(evidence) == (
        "postgres_service_log_retention_http_smoke=skipped "
        "reason=NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE"
    )


def test_postgres_service_log_retention_http_smoke_rejects_bad_profile_and_service() -> None:
    bad_profile = (
        service_log_retention_http_smoke.run_postgres_service_log_retention_http_smoke(
            environ={
                "NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE": "1",
                "NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE_PROFILE": "dev",
            }
        )
    )
    bad_service = (
        service_log_retention_http_smoke.run_postgres_service_log_retention_http_smoke(
            environ={
                "NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE": "1",
                "NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE_SERVICE": "unknown",
            }
        )
    )

    assert bad_profile["failure_code"] == "profile_not_allowed"
    assert bad_service["failure_code"] == "service_invalid"


def test_postgres_service_log_retention_http_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append(
            (service_id, profile)
        ),
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "database_pool_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "build_engine",
        lambda *args, **kwargs: FakeSqlEngine(),
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "build_session_factory",
        lambda engine: object(),
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "SqlAlchemyServiceLogStore",
        FakeRetentionServiceLogStore,
    )

    evidence = (
        service_log_retention_http_smoke.run_postgres_service_log_retention_http_smoke(
            environ={
                "NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE": "1",
                "NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE_SERVICE": "nex-cx",
            }
        )
    )

    assert evidence["status"] == "PASS"
    assert evidence["http_statuses"] == {
        "unauthorized": 401,
        "invalid": 422,
        "dry_run": 200,
        "blocked": 200,
        "execute": 200,
    }
    assert evidence["checks"] == {
        "auth_required": True,
        "invalid_dry_run_delete_enabled_rejected": True,
        "dry_run_http_succeeded_without_delete": True,
        "execute_without_delete_enabled_returns_blocked_execution": True,
        "execute_http_deleted_one_candidate": True,
        "store_state_guarded": True,
    }
    assert evidence["counts"]["execute_deleted_count"] == 1
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert "Bearer private" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert service_log_retention_http_smoke.summary_line(evidence) == (
        "postgres_service_log_retention_http_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env deleted=1"
    )


def test_postgres_service_log_retention_http_smoke_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenRetentionServiceLogStore(FakeRetentionServiceLogStore):
        def purge_retention_candidates(self, **kwargs: object) -> dict[str, object]:
            result = super().purge_retention_candidates(**kwargs)
            result["candidate_count"] = 0
            return result

    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "service_database_env",
        lambda *args, **kwargs: "NEX_CX_TEST_DATABASE_URL",
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "database_pool_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "build_engine",
        lambda *args, **kwargs: FakeSqlEngine(),
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "build_session_factory",
        lambda engine: object(),
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "SqlAlchemyServiceLogStore",
        BrokenRetentionServiceLogStore,
    )

    checks_failure = (
        service_log_retention_http_smoke.run_postgres_service_log_retention_http_smoke(
            environ={"NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE": "1"}
        )
    )

    assert checks_failure["status"] == "FAIL"
    assert checks_failure["failure_code"] == "checks_failed"
    assert checks_failure["database_env"] == "NEX_CX_TEST_DATABASE_URL"

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise service_log_retention_http_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = (
        service_log_retention_http_smoke.run_postgres_service_log_retention_http_smoke(
            environ={"NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE": "1"}
        )
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "build_engine",
        raise_runtime_error,
    )
    execution_failure = (
        service_log_retention_http_smoke.run_postgres_service_log_retention_http_smoke(
            environ={"NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE": "1"}
        )
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert service_log_retention_http_smoke.summary_line(execution_failure) == (
        "postgres_service_log_retention_http_smoke=fail "
        "service=nex-cx reason=execution_failed"
    )


def test_postgres_service_log_retention_http_smoke_helpers_cover_edges() -> None:
    assert (
        service_log_retention_http_smoke._redaction_safe(
            {"redacted_database_url": "postgresql://user:secret@localhost/db"}
        )
        is False
    )
    assert service_log_retention_http_smoke._checks(
        unauthorized={
            "_http_status": 401,
            "error_code": "AUTHORIZATION_HEADER_MISSING",
        },
        invalid={
            "_http_status": 422,
            "error_code": "service_log_retention.delete_enabled_invalid",
        },
        dry_run={
            "_http_status": 200,
            "retention_execution_schema_version": (
                "service_log_retention_execution.v1"
            ),
            "mode": "DRY_RUN",
            "execution_status": "SUCCEEDED",
            "candidate_count": 1,
            "deleted_count": 0,
            "request_id": "request-1",
        },
        blocked={
            "_http_status": 200,
            "mode": "EXECUTE",
            "execution_status": "BLOCKED",
            "candidate_count": 2,
            "deleted_count": 0,
            "blocked_reason": "delete_not_enabled",
        },
        execute={
            "_http_status": 200,
            "mode": "EXECUTE",
            "execution_status": "SUCCEEDED",
            "candidate_count": 2,
            "deleted_count": 1,
            "delete_enabled": True,
            "request_id": "request-1",
        },
        state={
            "old_001_remaining": False,
            "old_002_remaining": True,
            "fresh_remaining": True,
        },
    )["dry_run_http_succeeded_without_delete"] is False


def test_postgres_service_log_retention_http_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "load_env_file",
        lambda path: None,
    )
    monkeypatch.setattr(
        service_log_retention_http_smoke,
        "run_postgres_service_log_retention_http_smoke",
        lambda: {
            "smoke_schema_version": "postgres_service_log_retention_http_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_DB_SERVICE_LOG_RETENTION_HTTP_SMOKE is not enabled.",
        },
    )

    assert service_log_retention_http_smoke.main(["--summary"]) == 0
    assert "postgres_service_log_retention_http_smoke=skipped" in capsys.readouterr().out

    assert service_log_retention_http_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_postgres_operations_smoke_pack_skips_by_default() -> None:
    evidence = operations_smoke.run_postgres_operations_smoke_pack(environ={})

    assert evidence["status"] == "SKIPPED"
    assert operations_smoke.summary_line(evidence) == (
        "postgres_operations_smoke_pack=skipped reason=NEX_DB_OPERATIONS_SMOKE"
    )


def test_postgres_operations_smoke_pack_rejects_bad_profile_and_services() -> None:
    bad_profile = operations_smoke.run_postgres_operations_smoke_pack(
        environ={
            "NEX_DB_OPERATIONS_SMOKE": "1",
            "NEX_DB_OPERATIONS_SMOKE_PROFILE": "dev",
        }
    )
    bad_service = operations_smoke.run_postgres_operations_smoke_pack(
        environ={
            "NEX_DB_OPERATIONS_SMOKE": "1",
            "NEX_DB_OPERATIONS_SMOKE_SERVICES": "nex-cx,nex-unknown",
        }
    )
    no_services = operations_smoke.run_postgres_operations_smoke_pack(
        environ={
            "NEX_DB_OPERATIONS_SMOKE": "1",
            "NEX_DB_OPERATIONS_SMOKE_SERVICES": ", ,",
        }
    )

    assert bad_profile["status"] == "FAIL"
    assert bad_profile["failure_code"] == "profile_not_allowed"
    assert bad_service["failure_code"] == "service_invalid"
    assert no_services["failure_code"] == "service_selection_empty"


def test_postgres_operations_smoke_pack_reports_pass_without_leaking_database_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        operations_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        operations_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        operations_smoke,
        "check_database_readiness",
        lambda database_env, environ: {
            "name": "database",
            "ok": True,
            "database_env": database_env,
            "database_name": "nex_example_test",
            "database_user": "nex_example_user",
            "latency_ms": 1,
        },
    )

    def fake_jobqueue(environ: dict[str, str]) -> dict[str, object]:
        calls.append(
            (
                "jobqueue",
                environ["NEX_DB_JOBQUEUE_SMOKE_SERVICE"],
                environ["NEX_DB_JOBQUEUE_SMOKE_PROFILE"],
            )
        )
        return {
            "smoke_schema_version": "postgres_jobqueue_smoke.v1",
            "status": "PASS",
            "service_id": environ["NEX_DB_JOBQUEUE_SMOKE_SERVICE"],
            "profile": environ["NEX_DB_JOBQUEUE_SMOKE_PROFILE"],
            "database_env": f"{environ['NEX_DB_JOBQUEUE_SMOKE_SERVICE']}:test:env",
            "checks": {"enqueue": True},
            "redacted_database_url": "postgresql://user:***@localhost/db",
        }

    def fake_event(environ: dict[str, str]) -> dict[str, object]:
        calls.append(
            (
                "event",
                environ["NEX_DB_OPERATIONAL_EVENT_SMOKE_SERVICE"],
                environ["NEX_DB_OPERATIONAL_EVENT_SMOKE_PROFILE"],
            )
        )
        return {
            "smoke_schema_version": "postgres_operational_event_smoke.v1",
            "status": "PASS",
            "service_id": environ["NEX_DB_OPERATIONAL_EVENT_SMOKE_SERVICE"],
            "profile": environ["NEX_DB_OPERATIONAL_EVENT_SMOKE_PROFILE"],
            "database_env": f"{environ['NEX_DB_OPERATIONAL_EVENT_SMOKE_SERVICE']}:test:env",
            "checks": {"append": True},
            "redacted_database_url": "postgresql://user:***@localhost/db",
        }

    def fake_service_log(environ: dict[str, str]) -> dict[str, object]:
        calls.append(
            (
                "service_log",
                environ["NEX_DB_SERVICE_LOG_SMOKE_SERVICE"],
                environ["NEX_DB_SERVICE_LOG_SMOKE_PROFILE"],
            )
        )
        return {
            "smoke_schema_version": "postgres_service_log_smoke.v1",
            "status": "PASS",
            "service_id": environ["NEX_DB_SERVICE_LOG_SMOKE_SERVICE"],
            "profile": environ["NEX_DB_SERVICE_LOG_SMOKE_PROFILE"],
            "database_env": f"{environ['NEX_DB_SERVICE_LOG_SMOKE_SERVICE']}:test:env",
            "checks": {"append": True},
            "redacted_database_url": "postgresql://user:***@localhost/db",
        }

    monkeypatch.setattr(operations_smoke, "run_postgres_jobqueue_smoke", fake_jobqueue)
    monkeypatch.setattr(operations_smoke, "run_postgres_operational_event_smoke", fake_event)
    monkeypatch.setattr(
        operations_smoke,
        "run_postgres_service_log_smoke",
        fake_service_log,
    )

    evidence = operations_smoke.run_postgres_operations_smoke_pack(
        environ={
            "NEX_DB_OPERATIONS_SMOKE": "1",
            "NEX_DB_OPERATIONS_SMOKE_SERVICES": "nex-cx,nex-ag",
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["service_count"] == 2
    assert evidence["checks"] == {
        "all_readiness": True,
        "all_jobqueue": True,
        "all_operational_events": True,
        "all_service_logs": True,
    }
    assert "secret" not in str(evidence)
    assert operations_smoke.summary_line(evidence) == (
        "postgres_operations_smoke_pack=pass services=2 profile=test"
    )
    assert calls == [
        ("jobqueue", "nex-cx", "test"),
        ("event", "nex-cx", "test"),
        ("service_log", "nex-cx", "test"),
        ("jobqueue", "nex-ag", "test"),
        ("event", "nex-ag", "test"),
        ("service_log", "nex-ag", "test"),
    ]


def test_postgres_operations_smoke_pack_reports_readiness_and_subsmoke_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        operations_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        operations_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        operations_smoke,
        "check_database_readiness",
        lambda database_env, environ: {
            "name": "database",
            "ok": database_env.startswith("nex-cx"),
            "database_env": database_env,
            "error_code": "DATABASE_CONNECTION_FAILED",
            "latency_ms": 1,
        },
    )
    monkeypatch.setattr(
        operations_smoke,
        "run_postgres_jobqueue_smoke",
        lambda environ: {
            "smoke_schema_version": "postgres_jobqueue_smoke.v1",
            "status": "FAIL",
            "service_id": environ["NEX_DB_JOBQUEUE_SMOKE_SERVICE"],
            "profile": "test",
            "failure_code": "execution_failed",
        },
    )
    monkeypatch.setattr(
        operations_smoke,
        "run_postgres_operational_event_smoke",
        lambda environ: {
            "smoke_schema_version": "postgres_operational_event_smoke.v1",
            "status": "PASS",
            "service_id": environ["NEX_DB_OPERATIONAL_EVENT_SMOKE_SERVICE"],
            "profile": "test",
            "checks": {},
        },
    )
    monkeypatch.setattr(
        operations_smoke,
        "run_postgres_service_log_smoke",
        lambda environ: {
            "smoke_schema_version": "postgres_service_log_smoke.v1",
            "status": "PASS",
            "service_id": environ["NEX_DB_SERVICE_LOG_SMOKE_SERVICE"],
            "profile": "test",
            "checks": {},
        },
    )

    evidence = operations_smoke.run_postgres_operations_smoke_pack(
        environ={
            "NEX_DB_OPERATIONS_SMOKE": "1",
            "NEX_DB_OPERATIONS_SMOKE_SERVICES": "nex-cx,nex-ag",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "service_smoke_failed"
    assert evidence["failed_services"] == ["nex-cx", "nex-ag"]
    service_by_id = {service["service_id"]: service for service in evidence["services"]}
    assert service_by_id["nex-cx"]["failure_code"] == "subsmoke_failed"
    assert service_by_id["nex-cx"]["checks"]["jobqueue"] == "FAIL"
    assert service_by_id["nex-ag"]["failure_code"] == "readiness_failed"
    assert service_by_id["nex-ag"]["checks"] == {
        "readiness": "FAIL",
        "jobqueue": "SKIPPED",
        "operational_events": "SKIPPED",
        "service_logs": "SKIPPED",
    }
    assert operations_smoke.summary_line(evidence) == (
        "postgres_operations_smoke_pack=fail services=2 reason=service_smoke_failed"
    )


def test_postgres_operations_smoke_pack_reports_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        operations_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise operations_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(operations_smoke, "service_database_url", raise_migration_error)

    evidence = operations_smoke.run_postgres_operations_smoke_pack(
        environ={
            "NEX_DB_OPERATIONS_SMOKE": "1",
            "NEX_DB_OPERATIONS_SMOKE_SERVICES": "nex-cx",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["services"][0]["failure_code"] == "configuration_invalid"
    assert evidence["services"][0]["checks"]["readiness"] == "FAIL"


def test_postgres_operations_smoke_pack_helpers_cover_failure_edges() -> None:
    assert operations_smoke._readiness_summary(
        {
            "ok": False,
            "database_env": "NEX_CX_TEST_DATABASE_URL",
            "error_code": "DATABASE_CONNECTION_FAILED",
            "latency_ms": 1,
        }
    ) == {
        "ok": False,
        "database_env": "NEX_CX_TEST_DATABASE_URL",
        "error_code": "DATABASE_CONNECTION_FAILED",
        "latency_ms": 1,
    }
    assert operations_smoke._check_status({"checks": []}, "service_logs") is False


def test_postgres_operations_smoke_pack_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(operations_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        operations_smoke,
        "run_postgres_operations_smoke_pack",
        lambda: {
            "smoke_schema_version": "postgres_operations_smoke_pack.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_DB_OPERATIONS_SMOKE is not enabled.",
        },
    )

    assert operations_smoke.main(["--summary"]) == 0
    assert "postgres_operations_smoke_pack=skipped" in capsys.readouterr().out

    assert operations_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_postgres_test_smoke_suite_skips_by_default() -> None:
    evidence = postgres_suite_smoke.run_postgres_test_smoke_suite(environ={})

    assert evidence["status"] == "SKIPPED"
    assert postgres_suite_smoke.summary_line(evidence) == (
        "postgres_test_smoke_suite=skipped reason=NEX_POSTGRES_TEST_SMOKE_SUITE"
    )


def test_postgres_test_smoke_suite_rejects_bad_profile_services_and_primary() -> None:
    bad_profile = postgres_suite_smoke.run_postgres_test_smoke_suite(
        environ={
            "NEX_POSTGRES_TEST_SMOKE_SUITE": "1",
            "NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE": "dev",
        }
    )
    bad_service = postgres_suite_smoke.run_postgres_test_smoke_suite(
        environ={
            "NEX_POSTGRES_TEST_SMOKE_SUITE": "1",
            "NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES": "nex-cx,nex-unknown",
        }
    )
    no_services = postgres_suite_smoke.run_postgres_test_smoke_suite(
        environ={
            "NEX_POSTGRES_TEST_SMOKE_SUITE": "1",
            "NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES": ", ,",
        }
    )
    unsupported_primary = postgres_suite_smoke.run_postgres_test_smoke_suite(
        environ={
            "NEX_POSTGRES_TEST_SMOKE_SUITE": "1",
            "NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES": "nex-cx,nex-ag",
            "NEX_POSTGRES_TEST_SMOKE_SUITE_PRIMARY_SERVICE": "nex-ag",
        }
    )
    unselected_primary = postgres_suite_smoke.run_postgres_test_smoke_suite(
        environ={
            "NEX_POSTGRES_TEST_SMOKE_SUITE": "1",
            "NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES": "nex-ag",
        }
    )

    assert bad_profile["failure_code"] == "profile_not_allowed"
    assert bad_service["failure_code"] == "service_invalid"
    assert no_services["failure_code"] == "service_selection_empty"
    assert unsupported_primary["failure_code"] == "primary_service_not_supported"
    assert unselected_primary["failure_code"] == "primary_service_not_selected"


def test_postgres_test_smoke_suite_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_calls: list[tuple[str, str]] = []
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        postgres_suite_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "check_database_readiness",
        lambda database_env, environ: {
            "name": "database",
            "ok": True,
            "database_env": database_env,
            "database_name": "nex_example_test",
            "database_user": "nex_example_user",
            "latency_ms": 1,
        },
    )

    def fake_migrations(service_id: str, *, database_url: str, profile: str):
        migration_calls.append((service_id, profile))
        return SimpleNamespace(
            planned=("0023_schema_migrations_baseline",),
            applied=(),
            skipped=("0023_schema_migrations_baseline",),
        )

    def child_pass(name: str):
        def _run(environ: dict[str, str]) -> dict[str, object]:
            child_calls.append((name, environ["NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE"]))
            return {
                "smoke_schema_version": f"{name}.v1",
                "status": "PASS",
                "service_id": environ.get("NEX_DB_JOBQUEUE_SMOKE_SERVICE", "nex-cx"),
                "profile": "test",
                "database_env": "NEX_CX_TEST_DATABASE_URL",
                "checks": {"ok": True},
            }

        return _run

    monkeypatch.setattr(postgres_suite_smoke, "run_service_migrations", fake_migrations)
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_postgres_jobqueue_smoke",
        child_pass("postgres_jobqueue_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_postgres_job_replay_smoke",
        child_pass("postgres_job_replay_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_postgres_operational_event_smoke",
        child_pass("postgres_operational_event_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_postgres_service_log_smoke",
        child_pass("postgres_service_log_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_postgres_service_log_retention_smoke",
        child_pass("postgres_service_log_retention_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_postgres_service_log_retention_http_smoke",
        child_pass("postgres_service_log_retention_http_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_ag_service_log_retention_postgres_smoke",
        child_pass("ag_service_log_retention_postgres_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_postgres_operations_smoke_pack",
        child_pass("postgres_operations_smoke_pack"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_cx_retrieval_postgres_smoke",
        child_pass("cx_retrieval_postgres_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_cx_upload_ownership_postgres_smoke",
        child_pass("cx_upload_ownership_postgres_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_cx_upload_duplicate_postgres_smoke",
        child_pass("cx_upload_duplicate_postgres_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_cx_document_library_postgres_smoke",
        child_pass("cx_document_library_postgres_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_ag_retrieval_package_postgres_smoke",
        child_pass("ag_retrieval_package_postgres_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_cx_processing_postgres_jobqueue_smoke",
        child_pass("cx_processing_postgres_jobqueue_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_cx_processing_postgres_event_smoke",
        child_pass("cx_processing_postgres_event_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_cx_processing_postgres_persistence_smoke",
        child_pass("cx_processing_postgres_persistence_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_cx_processing_postgres_api_smoke",
        child_pass("cx_processing_postgres_api_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_ag_cx_processing_run_postgres_smoke",
        child_pass("ag_cx_processing_run_postgres_smoke"),
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_ag_cross_service_observability_smoke",
        child_pass("ag_cross_service_observability_smoke"),
    )

    evidence = postgres_suite_smoke.run_postgres_test_smoke_suite(
        environ={
            "NEX_POSTGRES_TEST_SMOKE_SUITE": "1",
            "NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES": "nex-cx,nex-ag",
            "NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE": "test",
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["service_count"] == 2
    assert all(evidence["checks"].values())
    assert evidence["stages"]["readiness"]["service_count"] == 2
    assert evidence["stages"]["migrations"]["services"][0]["skipped"] == [
        "0023_schema_migrations_baseline"
    ]
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test"), ("nex-ag", "test")]
    assert child_calls == [
        ("postgres_jobqueue_smoke", "test"),
        ("postgres_job_replay_smoke", "test"),
        ("postgres_operational_event_smoke", "test"),
        ("postgres_service_log_smoke", "test"),
        ("postgres_service_log_retention_smoke", "test"),
        ("postgres_service_log_retention_http_smoke", "test"),
        ("ag_service_log_retention_postgres_smoke", "test"),
        ("postgres_operations_smoke_pack", "test"),
        ("cx_retrieval_postgres_smoke", "test"),
        ("cx_upload_ownership_postgres_smoke", "test"),
        ("cx_upload_duplicate_postgres_smoke", "test"),
        ("cx_document_library_postgres_smoke", "test"),
        ("ag_retrieval_package_postgres_smoke", "test"),
        ("cx_processing_postgres_jobqueue_smoke", "test"),
        ("cx_processing_postgres_event_smoke", "test"),
        ("cx_processing_postgres_persistence_smoke", "test"),
        ("cx_processing_postgres_api_smoke", "test"),
        ("ag_cx_processing_run_postgres_smoke", "test"),
        ("ag_cross_service_observability_smoke", "test"),
    ]
    assert postgres_suite_smoke.summary_line(evidence) == (
        "postgres_test_smoke_suite=pass services=2 profile=test primary=nex-cx stages=21"
    )


def test_postgres_test_smoke_suite_stops_on_readiness_or_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        postgres_suite_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        postgres_suite_smoke,
        "check_database_readiness",
        lambda database_env, environ: {
            "name": "database",
            "ok": False,
            "database_env": database_env,
            "error_code": "DATABASE_CONNECTION_FAILED",
            "latency_ms": 1,
        },
    )
    readiness_failure = postgres_suite_smoke.run_postgres_test_smoke_suite(
        environ={
            "NEX_POSTGRES_TEST_SMOKE_SUITE": "1",
            "NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES": "nex-cx",
        }
    )

    assert readiness_failure["status"] == "FAIL"
    assert readiness_failure["failed_stage"] == "readiness"
    assert readiness_failure["checks"]["migrations"] is False

    monkeypatch.setattr(
        postgres_suite_smoke,
        "check_database_readiness",
        lambda database_env, environ: {
            "name": "database",
            "ok": True,
            "database_env": database_env,
            "database_name": "nex_example_test",
            "database_user": "nex_example_user",
            "latency_ms": 1,
        },
    )

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise postgres_suite_smoke.MigrationError("migration failed")

    monkeypatch.setattr(postgres_suite_smoke, "run_service_migrations", raise_migration_error)
    migration_failure = postgres_suite_smoke.run_postgres_test_smoke_suite(
        environ={
            "NEX_POSTGRES_TEST_SMOKE_SUITE": "1",
            "NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES": "nex-cx",
        }
    )

    assert migration_failure["status"] == "FAIL"
    assert migration_failure["failed_stage"] == "migrations"
    assert migration_failure["stages"]["migrations"]["failure_code"] == "migrations_failed"


def test_postgres_test_smoke_suite_readiness_summary_keeps_url_driver_evidence() -> None:
    summary = postgres_suite_smoke._readiness_summary(
        {
            "name": "database",
            "ok": True,
            "database_env": "NEX_CX_TEST_DATABASE_URL",
            "database_name": "nex_cx_test",
            "database_user": "nex_cx_user",
            "latency_ms": 1,
            "configured_url_drivername": "postgresql+psycopg",
            "connection_url_drivername": "postgresql",
            "url_normalized_for_psycopg": True,
        }
    )

    assert summary["ok"] is True
    assert summary["configured_url_drivername"] == "postgresql+psycopg"
    assert summary["connection_url_drivername"] == "postgresql"
    assert summary["url_normalized_for_psycopg"] is True

    failure = postgres_suite_smoke._readiness_summary(
        {
            "name": "database",
            "ok": False,
            "database_env": "NEX_CX_TEST_DATABASE_URL",
            "error_code": "DATABASE_CONNECTION_FAILED",
            "latency_ms": 1,
            "configured_url_drivername": "postgresql+psycopg",
            "connection_url_drivername": "postgresql",
            "url_normalized_for_psycopg": True,
        }
    )

    assert failure["ok"] is False
    assert failure["url_normalized_for_psycopg"] is True


def test_postgres_test_smoke_suite_reports_child_failure_and_main_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(postgres_suite_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        postgres_suite_smoke,
        "run_postgres_test_smoke_suite",
        lambda: {
            "smoke_schema_version": "postgres_test_smoke_suite.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_POSTGRES_TEST_SMOKE_SUITE is not enabled.",
        },
    )

    assert postgres_suite_smoke.main(["--summary"]) == 0
    assert "postgres_test_smoke_suite=skipped" in capsys.readouterr().out

    failure = postgres_suite_smoke._suite_evidence(
        profile="test",
        service_ids=("nex-cx",),
        primary_service_id="nex-cx",
        stages={
            "readiness": {"status": "PASS"},
            "migrations": {"status": "PASS"},
            "jobqueue": {"status": "FAIL", "failure_code": "execution_failed"},
        },
    )
    assert failure["status"] == "FAIL"
    assert failure["failed_stage"] == "jobqueue"
    assert postgres_suite_smoke.summary_line(failure) == (
        "postgres_test_smoke_suite=fail services=1 reason=stage_failed stage=jobqueue"
    )


def test_cx_retrieval_postgres_smoke_skips_by_default() -> None:
    evidence = cx_retrieval_smoke.run_cx_retrieval_postgres_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert cx_retrieval_smoke.summary_line(evidence) == (
        "cx_retrieval_postgres_smoke=skipped "
        "reason=NEX_CX_RETRIEVAL_POSTGRES_SMOKE"
    )


def test_cx_retrieval_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = cx_retrieval_smoke.run_cx_retrieval_postgres_smoke(
        environ={
            "NEX_CX_RETRIEVAL_POSTGRES_SMOKE": "1",
            "NEX_CX_RETRIEVAL_POSTGRES_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_cx_retrieval_postgres_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        cx_retrieval_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        cx_retrieval_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_retrieval_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append(
            (service_id, profile)
        ),
    )
    monkeypatch.setattr(
        cx_retrieval_smoke,
        "_execute_retrieval_repository_smoke",
        lambda database_url: {
            "retrieval_package_id": "retrieval-001",
            "document_id": "document-001",
            "evidence_count": 1,
            "checks": {
                "package_persisted": True,
                "evidence_persisted": True,
                "query_hash_persisted": True,
                "query_preview_bounded": True,
                "evidence_hash_persisted": True,
                "final_score_persisted": True,
                "repository_round_trip": True,
                "raw_payload_absent": True,
            },
        },
    )

    evidence = cx_retrieval_smoke.run_cx_retrieval_postgres_smoke(
        environ={"NEX_CX_RETRIEVAL_POSTGRES_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["checks"]["raw_payload_absent"] is True
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert cx_retrieval_smoke.summary_line(evidence) == (
        "cx_retrieval_postgres_smoke=pass service=nex-cx db_env=nex-cx:test:env"
    )


def test_cx_retrieval_postgres_smoke_reports_config_and_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise cx_retrieval_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        cx_retrieval_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = cx_retrieval_smoke.run_cx_retrieval_postgres_smoke(
        environ={"NEX_CX_RETRIEVAL_POSTGRES_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        cx_retrieval_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_retrieval_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        cx_retrieval_smoke,
        "_execute_retrieval_repository_smoke",
        raise_runtime_error,
    )
    execution_failure = cx_retrieval_smoke.run_cx_retrieval_postgres_smoke(
        environ={"NEX_CX_RETRIEVAL_POSTGRES_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert cx_retrieval_smoke.summary_line(execution_failure) == (
        "cx_retrieval_postgres_smoke=fail service=nex-cx reason=execution_failed"
    )


def test_cx_retrieval_postgres_smoke_execute_with_sqlite_fixture(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-retrieval-smoke.sqlite'}"
    engine = cx_retrieval_smoke.build_engine(database_url)
    _create_sqlite_cx_content_retrieval_tables(engine)

    evidence = cx_retrieval_smoke._execute_retrieval_repository_smoke(
        database_url=database_url,
    )

    assert evidence["checks"] == {
        "package_persisted": True,
        "evidence_persisted": True,
        "query_hash_persisted": True,
        "query_preview_bounded": True,
        "evidence_hash_persisted": True,
        "final_score_persisted": True,
        "repository_round_trip": True,
        "raw_payload_absent": True,
    }
    assert evidence["evidence_count"] == 1
    with engine.begin() as connection:
        remaining_packages = connection.execute(
            text("SELECT count(*) FROM cx_retrieval_packages")
        ).scalar_one()
        remaining_evidence = connection.execute(
            text("SELECT count(*) FROM cx_retrieval_evidence_items")
        ).scalar_one()
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_packages == 0
    assert remaining_evidence == 0
    assert remaining_content == 0
    assert remaining_sources == 0


def test_cx_retrieval_postgres_smoke_helpers_cover_error_edges(tmp_path) -> None:
    assert cx_retrieval_smoke.summary_line(
        {
            "smoke_schema_version": "cx_retrieval_postgres_smoke.v1",
            "status": "FAIL",
            "service_id": "nex-cx",
            "failure_code": "execution_failed",
        }
    ) == "cx_retrieval_postgres_smoke=fail service=nex-cx reason=execution_failed"

    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-retrieval-helper.sqlite'}"
    engine = cx_retrieval_smoke.build_engine(database_url)
    _create_sqlite_cx_content_retrieval_tables(engine)

    with pytest.raises(RuntimeError, match="stored retrieval package"):
        cx_retrieval_smoke._read_stored_retrieval_package(
            engine,
            retrieval_package_id="missing",
        )

    assert (
        cx_retrieval_smoke._read_smoke_retrieval_dump(
            engine,
            retrieval_package_id="missing",
        )
        == "[][]"
    )
    cx_retrieval_smoke._delete_smoke_retrieval_rows(
        engine,
        retrieval_package_id=None,
        document_id=None,
        source_file_id=None,
    )


def test_cx_retrieval_postgres_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cx_retrieval_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        cx_retrieval_smoke,
        "run_cx_retrieval_postgres_smoke",
        lambda: {
            "smoke_schema_version": "cx_retrieval_postgres_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_CX_RETRIEVAL_POSTGRES_SMOKE is not enabled.",
        },
    )

    assert cx_retrieval_smoke.main(["--summary"]) == 0
    assert "cx_retrieval_postgres_smoke=skipped" in capsys.readouterr().out

    assert cx_retrieval_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_ag_retrieval_package_postgres_smoke_skips_by_default() -> None:
    evidence = ag_retrieval_postgres_smoke.run_ag_retrieval_package_postgres_smoke(
        environ={}
    )

    assert evidence["status"] == "SKIPPED"
    assert ag_retrieval_postgres_smoke.summary_line(evidence) == (
        "ag_retrieval_package_postgres_smoke=skipped "
        "reason=NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE"
    )


def test_ag_retrieval_package_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = ag_retrieval_postgres_smoke.run_ag_retrieval_package_postgres_smoke(
        environ={
            "NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE": "1",
            "NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_ag_retrieval_package_postgres_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append(
            (service_id, profile)
        ),
    )
    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "_execute_ag_retrieval_package_postgres_smoke",
        lambda database_url, database_env, environ: {
            "retrieval_package_id": "retrieval-001",
            "request_id": "request-001",
            "trace_id": "0" * 32,
            "projection_versions": {
                "list": "ag_retrieval_package_operations_projection.v1",
                "detail": "ag_retrieval_package_detail_projection.v1",
                "trace": "ag_cross_service_trace_timeline_projection.v1",
            },
            "http_statuses": {"list": 200, "detail": 200, "trace": 200},
            "counts": {
                "list_total": 1,
                "detail_evidence_items": 1,
                "trace_timeline_total": 1,
            },
            "checks": {
                "list_projection_reads_postgres": True,
                "list_filter_returns_seeded_package": True,
                "detail_projection_redacts_evidence": True,
                "permission_projection_excludes_principal_id": True,
                "trace_timeline_correlates_package": True,
                "raw_values_absent_from_ag_evidence": True,
            },
            "raw_values": ["raw query", "raw evidence", "raw principal"],
        },
    )

    evidence = ag_retrieval_postgres_smoke.run_ag_retrieval_package_postgres_smoke(
        environ={"NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert evidence["counts"] == {
        "list_total": 1,
        "detail_evidence_items": 1,
        "trace_timeline_total": 1,
    }
    assert "secret" not in str(evidence)
    assert "raw_values" not in evidence
    assert migration_calls == [("nex-cx", "test")]
    assert ag_retrieval_postgres_smoke.summary_line(evidence) == (
        "ag_retrieval_package_postgres_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env "
        "list=1 detail_evidence=1 timeline=1"
    )


def test_ag_retrieval_package_postgres_smoke_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "service_database_env",
        lambda *args, **kwargs: "NEX_CX_TEST_DATABASE_URL",
    )

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise ag_retrieval_postgres_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = (
        ag_retrieval_postgres_smoke.run_ag_retrieval_package_postgres_smoke(
            environ={"NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE": "1"}
        )
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "_execute_ag_retrieval_package_postgres_smoke",
        lambda *args, **kwargs: {
            "failure_code": "checks_failed",
            "detail": "checks failed",
            "checks": {"ok": False},
            "raw_values": ["raw"],
        },
    )
    checks_failure = (
        ag_retrieval_postgres_smoke.run_ag_retrieval_package_postgres_smoke(
            environ={"NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE": "1"}
        )
    )

    assert checks_failure["status"] == "FAIL"
    assert checks_failure["failure_code"] == "checks_failed"
    assert checks_failure["checks"] == {"ok": False}

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "_execute_ag_retrieval_package_postgres_smoke",
        raise_runtime_error,
    )
    execution_failure = (
        ag_retrieval_postgres_smoke.run_ag_retrieval_package_postgres_smoke(
            environ={"NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE": "1"}
        )
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert ag_retrieval_postgres_smoke.summary_line(execution_failure) == (
        "ag_retrieval_package_postgres_smoke=fail "
        "service=nex-cx reason=execution_failed"
    )


def test_ag_retrieval_package_postgres_smoke_execute_with_sqlite_fixture(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'ag-retrieval-smoke.sqlite'}"
    engine = ag_retrieval_postgres_smoke.build_engine(database_url)
    _create_sqlite_cx_content_retrieval_tables(engine)

    evidence = ag_retrieval_postgres_smoke._execute_ag_retrieval_package_postgres_smoke(
        database_url=database_url,
        database_env="NEX_CX_TEST_DATABASE_URL",
        environ={},
    )

    assert evidence["http_statuses"] == {"list": 200, "detail": 200, "trace": 200}
    assert evidence["counts"] == {
        "list_total": 1,
        "detail_evidence_items": 1,
        "trace_timeline_total": 1,
    }
    assert all(evidence["checks"].values())
    assert ag_retrieval_postgres_smoke._redaction_safe(
        {key: value for key, value in evidence.items() if key != "raw_values"},
        evidence["raw_values"],
    )
    with engine.begin() as connection:
        remaining = {
            "packages": connection.execute(
                text("SELECT count(*) FROM cx_retrieval_packages")
            ).scalar_one(),
            "evidence": connection.execute(
                text("SELECT count(*) FROM cx_retrieval_evidence_items")
            ).scalar_one(),
            "chunks": connection.execute(
                text("SELECT count(*) FROM cx_chunks")
            ).scalar_one(),
            "chunk_sets": connection.execute(
                text("SELECT count(*) FROM cx_chunk_sets")
            ).scalar_one(),
            "extractions": connection.execute(
                text("SELECT count(*) FROM cx_extraction_artifacts")
            ).scalar_one(),
            "content": connection.execute(
                text("SELECT count(*) FROM cx_content_objects")
            ).scalar_one(),
            "sources": connection.execute(
                text("SELECT count(*) FROM cx_source_files")
            ).scalar_one(),
        }
    assert remaining == {
        "packages": 0,
        "evidence": 0,
        "chunks": 0,
        "chunk_sets": 0,
        "extractions": 0,
        "content": 0,
        "sources": 0,
    }


def test_ag_retrieval_package_postgres_smoke_helpers_cover_edges() -> None:
    assert ag_retrieval_postgres_smoke._json_sql_expression(
        SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        "payload",
    ) == "CAST(:payload AS jsonb)"
    assert ag_retrieval_postgres_smoke._json_sql_expression(
        SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
        "payload",
    ) == ":payload"
    assert (
        ag_retrieval_postgres_smoke._redaction_safe({"value": "secret"}, [])
        is False
    )
    assert ag_retrieval_postgres_smoke._preview("abcdef", max_chars=3) == "abc"
    assert ag_retrieval_postgres_smoke.summary_line(
        {
            "smoke_schema_version": "ag_retrieval_package_postgres_smoke.v1",
            "status": "FAIL",
            "service_id": "nex-cx",
            "failure_code": "checks_failed",
        }
    ) == "ag_retrieval_package_postgres_smoke=fail service=nex-cx reason=checks_failed"

    bad_checks = ag_retrieval_postgres_smoke._checks(
        list_response={
            "_http_status": 503,
            "projection_schema_version": "wrong",
            "source_statuses": {},
            "summary": {"total": 0},
            "retrieval_packages": [],
        },
        detail_response={
            "_http_status": 404,
            "projection_schema_version": "wrong",
            "summary": {},
            "evidence_items": [],
        },
        trace_response={
            "_http_status": 200,
            "projection_schema_version": "wrong",
            "retrieval_package_source_statuses": {"nex-cx": {"status": "UNAVAILABLE"}},
            "timeline": [],
        },
        refs={
            "retrieval_package_id": "missing",
            "trace_id": "0" * 32,
            "request_id": "request",
        },
        raw_values=["raw leak"],
    )

    assert bad_checks == {
        "list_projection_reads_postgres": False,
        "list_filter_returns_seeded_package": False,
        "detail_projection_redacts_evidence": False,
        "permission_projection_excludes_principal_id": False,
        "trace_timeline_correlates_package": False,
        "raw_values_absent_from_ag_evidence": True,
    }


def test_ag_retrieval_package_postgres_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "load_env_file",
        lambda path: None,
    )
    monkeypatch.setattr(
        ag_retrieval_postgres_smoke,
        "run_ag_retrieval_package_postgres_smoke",
        lambda: {
            "smoke_schema_version": "ag_retrieval_package_postgres_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": (
                "NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE is not enabled."
            ),
        },
    )

    assert ag_retrieval_postgres_smoke.main(["--summary"]) == 0
    assert "ag_retrieval_package_postgres_smoke=skipped" in capsys.readouterr().out

    assert ag_retrieval_postgres_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_cx_processing_postgres_jobqueue_smoke_skips_by_default() -> None:
    evidence = cx_processing_smoke.run_cx_processing_postgres_jobqueue_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert cx_processing_smoke.summary_line(evidence) == (
        "cx_processing_postgres_jobqueue_smoke=skipped "
        "reason=NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE"
    )


def test_cx_processing_postgres_jobqueue_smoke_rejects_non_test_profile() -> None:
    evidence = cx_processing_smoke.run_cx_processing_postgres_jobqueue_smoke(
        environ={
            "NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE": "1",
            "NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_cx_processing_postgres_jobqueue_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        cx_processing_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        cx_processing_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_processing_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append((service_id, profile)),
    )
    monkeypatch.setattr(
        cx_processing_smoke,
        "_execute_processing_route_smoke",
        lambda database_url, runtime_environ: {
            "pipeline_run_id": "pipeline-001",
            "document_id": "doc-001",
            "job_id": "job-001",
            "checks": {
                "route_succeeded": True,
                "runtime_mode": True,
                "response_job_succeeded": True,
                "stored_job_succeeded": True,
                "stored_job_type": True,
                "stored_attempt_count": True,
                "stored_subject": True,
            },
        },
    )

    evidence = cx_processing_smoke.run_cx_processing_postgres_jobqueue_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["checks"]["stored_job_succeeded"] is True
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert cx_processing_smoke.summary_line(evidence) == (
        "cx_processing_postgres_jobqueue_smoke=pass service=nex-cx db_env=nex-cx:test:env"
    )


def test_cx_processing_postgres_jobqueue_smoke_reports_config_and_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise cx_processing_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(cx_processing_smoke, "service_database_url", raise_migration_error)
    config_failure = cx_processing_smoke.run_cx_processing_postgres_jobqueue_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        cx_processing_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(cx_processing_smoke, "run_service_migrations", lambda *args, **kwargs: None)

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cx_processing_smoke, "_execute_processing_route_smoke", raise_runtime_error)
    execution_failure = cx_processing_smoke.run_cx_processing_postgres_jobqueue_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert cx_processing_smoke.summary_line(execution_failure) == (
        "cx_processing_postgres_jobqueue_smoke=fail service=nex-cx reason=execution_failed"
    )


def test_cx_processing_postgres_jobqueue_smoke_execute_route_with_sqlite_fixture(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-processing-smoke.sqlite'}"
    engine = cx_processing_smoke.build_engine(database_url)
    _create_sqlite_service_jobs_table(engine)

    evidence = cx_processing_smoke._execute_processing_route_smoke(
        database_url=database_url,
        runtime_environ={
            "NEX_CX_DATABASE_URL": database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
        },
    )

    assert evidence["checks"] == {
        "route_succeeded": True,
        "runtime_mode": True,
        "response_job_succeeded": True,
        "stored_job_succeeded": True,
        "stored_job_type": True,
        "stored_attempt_count": True,
        "stored_subject": True,
    }
    assert isinstance(evidence["job_id"], str)
    assert evidence["job_id"]
    with engine.begin() as connection:
        remaining = connection.execute(text("SELECT count(*) FROM service_jobs")).scalar_one()
    assert remaining == 0


def test_cx_processing_postgres_jobqueue_smoke_helpers_cover_error_edges(tmp_path) -> None:
    assert cx_processing_smoke.StaticMoEmbeddingClient().create_embeddings(
        ["one", "two"],
        alias="alias",
        request_id="request",
        trace_id="trace",
    )["usage"]["total_tokens"] == 2

    database_url = f"sqlite+pysqlite:///{tmp_path / 'missing-job.sqlite'}"
    engine = cx_processing_smoke.build_engine(database_url)
    _create_sqlite_service_jobs_table(engine)

    with pytest.raises(RuntimeError, match="stored processing job"):
        cx_processing_smoke._read_stored_processing_job(engine, job_id="missing")

    cx_processing_smoke._delete_smoke_processing_jobs(
        engine,
        trace_id="trace",
        request_id="request",
        job_id=None,
    )


def test_cx_processing_postgres_jobqueue_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cx_processing_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        cx_processing_smoke,
        "run_cx_processing_postgres_jobqueue_smoke",
        lambda: {
            "smoke_schema_version": "cx_processing_postgres_jobqueue_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE is not enabled.",
        },
    )

    assert cx_processing_smoke.main(["--summary"]) == 0
    assert "cx_processing_postgres_jobqueue_smoke=skipped" in capsys.readouterr().out

    assert cx_processing_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_cx_processing_postgres_event_smoke_skips_by_default() -> None:
    evidence = cx_processing_event_smoke.run_cx_processing_postgres_event_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert cx_processing_event_smoke.summary_line(evidence) == (
        "cx_processing_postgres_event_smoke=skipped "
        "reason=NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE"
    )


def test_cx_processing_postgres_event_smoke_rejects_non_test_profile() -> None:
    evidence = cx_processing_event_smoke.run_cx_processing_postgres_event_smoke(
        environ={
            "NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE": "1",
            "NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_cx_processing_postgres_event_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        cx_processing_event_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        cx_processing_event_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_processing_event_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append((service_id, profile)),
    )
    monkeypatch.setattr(
        cx_processing_event_smoke,
        "_execute_processing_event_route_smoke",
        lambda database_url, runtime_environ: {
            "pipeline_run_id": "pipeline-001",
            "document_id": "doc-001",
            "job_id": "job-001",
            "event_ids": ["event-started", "event-succeeded"],
            "checks": {
                "route_succeeded": True,
                "runtime_mode": True,
                "started_event_persisted": True,
                "succeeded_event_persisted": True,
                "failed_event_absent": True,
                "redaction_safe": True,
            },
        },
    )

    evidence = cx_processing_event_smoke.run_cx_processing_postgres_event_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["checks"]["succeeded_event_persisted"] is True
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert cx_processing_event_smoke.summary_line(evidence) == (
        "cx_processing_postgres_event_smoke=pass service=nex-cx db_env=nex-cx:test:env"
    )


def test_cx_processing_postgres_event_smoke_reports_config_and_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise cx_processing_event_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(cx_processing_event_smoke, "service_database_url", raise_migration_error)
    config_failure = cx_processing_event_smoke.run_cx_processing_postgres_event_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        cx_processing_event_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_processing_event_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        cx_processing_event_smoke,
        "_execute_processing_event_route_smoke",
        raise_runtime_error,
    )
    execution_failure = cx_processing_event_smoke.run_cx_processing_postgres_event_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert cx_processing_event_smoke.summary_line(execution_failure) == (
        "cx_processing_postgres_event_smoke=fail service=nex-cx reason=execution_failed"
    )


def test_cx_processing_postgres_event_smoke_execute_route_with_sqlite_fixture(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-processing-event-smoke.sqlite'}"
    engine = cx_processing_event_smoke.build_engine(database_url)
    _create_sqlite_service_jobs_table(engine)
    _create_sqlite_service_operational_events_table(engine)
    _create_sqlite_service_worker_heartbeats_table(engine)

    evidence = cx_processing_event_smoke._execute_processing_event_route_smoke(
        database_url=database_url,
        runtime_environ={
            "NEX_CX_DATABASE_URL": database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
        },
    )

    assert evidence["checks"] == {
        "route_succeeded": True,
        "runtime_mode": True,
        "started_event_persisted": True,
        "succeeded_event_persisted": True,
        "failed_event_absent": True,
        "worker_busy_event_persisted": True,
        "worker_idle_event_persisted": True,
        "worker_error_event_absent": True,
        "started_event_id": True,
        "succeeded_event_id": True,
        "worker_busy_event_id": True,
        "worker_idle_event_id": True,
        "started_severity": True,
        "succeeded_severity": True,
        "worker_busy_severity": True,
        "worker_idle_severity": True,
        "started_subject": True,
        "succeeded_subject": True,
        "worker_busy_subject": True,
        "worker_idle_subject": True,
        "started_details": True,
        "succeeded_details": True,
        "worker_busy_details": True,
        "worker_idle_details": True,
        "redaction_safe": True,
    }
    assert len(evidence["event_ids"]) == 4
    with engine.begin() as connection:
        remaining_jobs = connection.execute(text("SELECT count(*) FROM service_jobs")).scalar_one()
        remaining_events = connection.execute(
            text("SELECT count(*) FROM service_operational_events")
        ).scalar_one()
        remaining_heartbeats = connection.execute(
            text("SELECT count(*) FROM service_worker_heartbeats")
        ).scalar_one()
    assert remaining_jobs == 0
    assert remaining_events == 0
    assert remaining_heartbeats == 0


def test_cx_processing_postgres_event_smoke_helpers_cover_event_edges(tmp_path) -> None:
    pipeline_run = {
        "pipeline_run_id": "pipeline-001",
        "job": {"job_id": "job-001"},
        "step_summary": {"total": 6, "succeeded": 6, "skipped": 0, "failed": 0},
    }
    started_event = {
        "event_id": cx_processing_event_smoke.processing_event_id(
            pipeline_run_id="pipeline-001",
            event_type=cx_processing_event_smoke.PROCESSING_EVENT_STARTED,
        ),
        "event_type": cx_processing_event_smoke.PROCESSING_EVENT_STARTED,
        "severity": "INFO",
        "subject_type": "cx.document",
        "subject_id": "doc-001",
        "details": {
            "pipeline_run_id": "pipeline-001",
            "job_id": "job-001",
            "job_status": "RUNNING",
        },
    }
    succeeded_event = {
        "event_id": cx_processing_event_smoke.processing_event_id(
            pipeline_run_id="pipeline-001",
            event_type=cx_processing_event_smoke.PROCESSING_EVENT_SUCCEEDED,
        ),
        "event_type": cx_processing_event_smoke.PROCESSING_EVENT_SUCCEEDED,
        "severity": "INFO",
        "subject_type": "cx.document",
        "subject_id": "doc-001",
        "details": {
            "pipeline_run_id": "pipeline-001",
            "job_id": "job-001",
            "job_status": "SUCCEEDED",
            "step_summary": pipeline_run["step_summary"],
        },
    }
    busy_event = {
        "event_id": cx_processing_event_smoke.processing_worker_event_id(
            pipeline_run_id="pipeline-001",
            event_type=cx_processing_event_smoke.PROCESSING_WORKER_EVENT_BUSY,
        ),
        "event_type": cx_processing_event_smoke.PROCESSING_WORKER_EVENT_BUSY,
        "severity": "INFO",
        "subject_type": "worker",
        "subject_id": cx_processing_event_smoke.CX_PROCESSING_WORKER_ID,
        "details": {
            "worker_id": cx_processing_event_smoke.CX_PROCESSING_WORKER_ID,
            "worker_type": cx_processing_event_smoke.CX_PROCESSING_WORKER_TYPE,
            "worker_status": "BUSY",
            "pipeline_run_id": "pipeline-001",
            "document_id": "doc-001",
            "heartbeat_emit_ok": True,
            "active_job_id": "job-001",
            "job_id": "job-001",
            "job_status": "RUNNING",
        },
    }
    idle_event = {
        "event_id": cx_processing_event_smoke.processing_worker_event_id(
            pipeline_run_id="pipeline-001",
            event_type=cx_processing_event_smoke.PROCESSING_WORKER_EVENT_IDLE,
        ),
        "event_type": cx_processing_event_smoke.PROCESSING_WORKER_EVENT_IDLE,
        "severity": "INFO",
        "subject_type": "worker",
        "subject_id": cx_processing_event_smoke.CX_PROCESSING_WORKER_ID,
        "details": {
            "worker_id": cx_processing_event_smoke.CX_PROCESSING_WORKER_ID,
            "worker_type": cx_processing_event_smoke.CX_PROCESSING_WORKER_TYPE,
            "worker_status": "IDLE",
            "pipeline_run_id": "pipeline-001",
            "document_id": "doc-001",
            "heartbeat_emit_ok": True,
            "job_id": "job-001",
            "job_status": "SUCCEEDED",
            "step_summary": pipeline_run["step_summary"],
        },
    }

    checks = cx_processing_event_smoke._processing_event_checks(
        stored_events=[started_event, succeeded_event, busy_event, idle_event],
        pipeline_run=pipeline_run,
        document_id="doc-001",
    )
    missing_checks = cx_processing_event_smoke._processing_event_checks(
        stored_events=[],
        pipeline_run=pipeline_run,
        document_id="doc-001",
    )

    assert all(checks.values())
    assert missing_checks["started_event_persisted"] is False
    assert missing_checks["failed_event_absent"] is True
    assert cx_processing_event_smoke._event_value(None, "event_id") is None
    assert cx_processing_event_smoke._event_details(None) == {}
    assert cx_processing_event_smoke._event_details({"details": []}) == {}
    assert cx_processing_event_smoke._subject_matches(None, document_id="doc-001") is False
    assert cx_processing_event_smoke._worker_subject_matches(None) is False
    assert cx_processing_event_smoke._json_loads(None, default={"fallback": True}) == {
        "fallback": True
    }
    assert cx_processing_event_smoke._json_loads({"already": "dict"}, default={}) == {
        "already": "dict"
    }
    assert cx_processing_event_smoke._json_loads(b'{"from":"bytes"}', default={}) == {
        "from": "bytes"
    }
    assert cx_processing_event_smoke._json_loads(123, default={"fallback": True}) == {
        "fallback": True
    }
    assert (
        cx_processing_event_smoke._events_are_redaction_safe(
            [{"details": {"source_text": "hidden"}}]
        )
        is False
    )

    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-processing-event-helper.sqlite'}"
    engine = cx_processing_event_smoke.build_engine(database_url)
    _create_sqlite_service_operational_events_table(engine)
    assert (
        cx_processing_event_smoke._read_stored_processing_events(
            engine,
            trace_id="missing",
            request_id="missing",
        )
        == []
    )
    cx_processing_event_smoke._delete_smoke_processing_events(
        engine,
        trace_id="missing",
        request_id="missing",
    )
    _create_sqlite_service_worker_heartbeats_table(engine)
    cx_processing_event_smoke._delete_smoke_worker_heartbeat(engine)


def test_cx_processing_postgres_event_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cx_processing_event_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        cx_processing_event_smoke,
        "run_cx_processing_postgres_event_smoke",
        lambda: {
            "smoke_schema_version": "cx_processing_postgres_event_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE is not enabled.",
        },
    )

    assert cx_processing_event_smoke.main(["--summary"]) == 0
    assert "cx_processing_postgres_event_smoke=skipped" in capsys.readouterr().out

    assert cx_processing_event_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_cx_processing_postgres_persistence_smoke_skips_by_default() -> None:
    evidence = cx_processing_persistence_smoke.run_cx_processing_postgres_persistence_smoke(
        environ={}
    )

    assert evidence["status"] == "SKIPPED"
    assert cx_processing_persistence_smoke.summary_line(evidence) == (
        "cx_processing_postgres_persistence_smoke=skipped "
        "reason=NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE"
    )


def test_cx_processing_postgres_persistence_smoke_rejects_non_test_profile() -> None:
    evidence = cx_processing_persistence_smoke.run_cx_processing_postgres_persistence_smoke(
        environ={
            "NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE": "1",
            "NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_cx_processing_postgres_persistence_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        cx_processing_persistence_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        cx_processing_persistence_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_processing_persistence_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append((service_id, profile)),
    )
    monkeypatch.setattr(
        cx_processing_persistence_smoke,
        "_execute_processing_persistence_smoke",
        lambda database_url: {
            "document_id": "doc-001",
            "succeeded_pipeline_run_id": "pipeline-succeeded",
            "failed_pipeline_run_id": "pipeline-failed",
            "step_count": 2,
            "checks": {
                "queued_run_persisted": True,
                "queued_step_count_zero": True,
                "queued_run_upserted_to_succeeded": True,
                "succeeded_step_persisted": True,
                "output_ref_hash_persisted": True,
                "failed_step_persisted": True,
                "failed_error_hash_persisted": True,
                "repository_round_trip": True,
                "latest_round_trip": True,
                "raw_payload_absent": True,
            },
        },
    )

    evidence = cx_processing_persistence_smoke.run_cx_processing_postgres_persistence_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["checks"]["failed_error_hash_persisted"] is True
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert cx_processing_persistence_smoke.summary_line(evidence) == (
        "cx_processing_postgres_persistence_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env"
    )


def test_cx_processing_postgres_persistence_smoke_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise cx_processing_persistence_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        cx_processing_persistence_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = cx_processing_persistence_smoke.run_cx_processing_postgres_persistence_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        cx_processing_persistence_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_processing_persistence_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        cx_processing_persistence_smoke,
        "_execute_processing_persistence_smoke",
        raise_runtime_error,
    )
    execution_failure = cx_processing_persistence_smoke.run_cx_processing_postgres_persistence_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert cx_processing_persistence_smoke.summary_line(execution_failure) == (
        "cx_processing_postgres_persistence_smoke=fail "
        "service=nex-cx reason=execution_failed"
    )


def test_cx_processing_postgres_persistence_smoke_execute_with_sqlite_fixture(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-processing-persistence.sqlite'}"
    engine = cx_processing_persistence_smoke.build_engine(database_url)
    _create_sqlite_cx_processing_persistence_tables(engine)

    evidence = cx_processing_persistence_smoke._execute_processing_persistence_smoke(
        database_url=database_url,
    )

    assert evidence["checks"] == {
        "queued_run_persisted": True,
        "queued_step_count_zero": True,
        "queued_run_upserted_to_succeeded": True,
        "succeeded_step_persisted": True,
        "output_ref_hash_persisted": True,
        "failed_step_persisted": True,
        "failed_error_hash_persisted": True,
        "repository_round_trip": True,
        "latest_round_trip": True,
        "raw_payload_absent": True,
    }
    assert evidence["step_count"] == 2
    with engine.begin() as connection:
        remaining_runs = connection.execute(
            text("SELECT count(*) FROM cx_document_processing_runs")
        ).scalar_one()
        remaining_steps = connection.execute(
            text("SELECT count(*) FROM cx_document_processing_steps")
        ).scalar_one()
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_runs == 0
    assert remaining_steps == 0
    assert remaining_content == 0
    assert remaining_sources == 0


def test_cx_processing_postgres_persistence_smoke_helpers_cover_edges(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-processing-helper.sqlite'}"
    engine = cx_processing_persistence_smoke.build_engine(database_url)
    _create_sqlite_cx_processing_persistence_tables(engine)

    with pytest.raises(RuntimeError, match="stored processing run"):
        cx_processing_persistence_smoke._read_stored_processing_run(
            engine,
            pipeline_run_id="missing",
        )

    assert (
        cx_processing_persistence_smoke._redaction_safe(
            "safe payload",
            forbidden_fragments=["secret"],
        )
        is True
    )
    assert (
        cx_processing_persistence_smoke._redaction_safe(
            "unsafe secret payload",
            forbidden_fragments=["secret"],
        )
        is False
    )
    assert cx_processing_persistence_smoke._sha256_json({"b": 2, "a": 1}) == (
        cx_processing_persistence_smoke._sha256_text('{"a":1,"b":2}')
    )
    cx_processing_persistence_smoke._delete_smoke_processing_persistence_rows(
        engine,
        pipeline_run_ids=["missing"],
        document_id=None,
        source_file_id=None,
    )


def test_cx_processing_postgres_persistence_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cx_processing_persistence_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        cx_processing_persistence_smoke,
        "run_cx_processing_postgres_persistence_smoke",
        lambda: {
            "smoke_schema_version": "cx_processing_postgres_persistence_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE is not enabled.",
        },
    )

    assert cx_processing_persistence_smoke.main(["--summary"]) == 0
    assert "cx_processing_postgres_persistence_smoke=skipped" in capsys.readouterr().out

    assert cx_processing_persistence_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_cx_processing_postgres_api_smoke_skips_by_default() -> None:
    evidence = cx_processing_api_smoke.run_cx_processing_postgres_api_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert cx_processing_api_smoke.summary_line(evidence) == (
        "cx_processing_postgres_api_smoke=skipped "
        "reason=NEX_CX_PROCESSING_POSTGRES_API_SMOKE"
    )


def test_cx_processing_postgres_api_smoke_rejects_non_test_profile() -> None:
    evidence = cx_processing_api_smoke.run_cx_processing_postgres_api_smoke(
        environ={
            "NEX_CX_PROCESSING_POSTGRES_API_SMOKE": "1",
            "NEX_CX_PROCESSING_POSTGRES_API_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_cx_processing_postgres_api_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        cx_processing_api_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        cx_processing_api_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_processing_api_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append((service_id, profile)),
    )
    monkeypatch.setattr(
        cx_processing_api_smoke,
        "_execute_processing_api_smoke",
        lambda database_url, runtime_environ: {
            "document_id": "doc-001",
            "pipeline_run_id": "pipeline-001",
            "step_count": 1,
            "checks": {
                "api_status_ok": True,
                "runtime_mode": True,
                "persisted_projection_schema": True,
                "latest_pipeline_run_returned": True,
                "memory_fallback_bypassed": True,
                "job_id_projected": True,
                "steps_included": True,
                "failed_step_projected": True,
                "failed_error_hash_projected": True,
                "repository_latest_round_trip": True,
                "raw_payload_absent": True,
            },
        },
    )

    evidence = cx_processing_api_smoke.run_cx_processing_postgres_api_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_API_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["checks"]["memory_fallback_bypassed"] is True
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert cx_processing_api_smoke.summary_line(evidence) == (
        "cx_processing_postgres_api_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env"
    )


def test_cx_processing_postgres_api_smoke_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise cx_processing_api_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        cx_processing_api_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = cx_processing_api_smoke.run_cx_processing_postgres_api_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_API_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        cx_processing_api_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_processing_api_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        cx_processing_api_smoke,
        "_execute_processing_api_smoke",
        raise_runtime_error,
    )
    execution_failure = cx_processing_api_smoke.run_cx_processing_postgres_api_smoke(
        environ={"NEX_CX_PROCESSING_POSTGRES_API_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert cx_processing_api_smoke.summary_line(execution_failure) == (
        "cx_processing_postgres_api_smoke=fail "
        "service=nex-cx reason=execution_failed"
    )


def test_cx_processing_postgres_api_smoke_execute_with_sqlite_fixture(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-processing-api.sqlite'}"
    engine = cx_processing_api_smoke.build_engine(database_url)
    _create_sqlite_cx_processing_persistence_tables(engine)

    evidence = cx_processing_api_smoke._execute_processing_api_smoke(
        database_url=database_url,
        runtime_environ={
            "NEX_CX_DATABASE_URL": database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
        },
    )

    assert evidence["checks"] == {
        "api_status_ok": True,
        "runtime_mode": True,
        "persisted_projection_schema": True,
        "latest_pipeline_run_returned": True,
        "memory_fallback_bypassed": True,
        "job_id_projected": True,
        "steps_included": True,
        "failed_step_projected": True,
        "failed_error_hash_projected": True,
        "repository_latest_round_trip": True,
        "raw_payload_absent": True,
    }
    assert evidence["step_count"] == 1
    with engine.begin() as connection:
        remaining_runs = connection.execute(
            text("SELECT count(*) FROM cx_document_processing_runs")
        ).scalar_one()
        remaining_steps = connection.execute(
            text("SELECT count(*) FROM cx_document_processing_steps")
        ).scalar_one()
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_runs == 0
    assert remaining_steps == 0
    assert remaining_content == 0
    assert remaining_sources == 0


def test_cx_processing_postgres_api_smoke_helpers_cover_edges() -> None:
    assert cx_processing_api_smoke._failed_step_projected({}) is False
    assert (
        cx_processing_api_smoke._failed_step_projected(
            {"steps": [{"step_id": "summary", "status": "FAILED"}]}
        )
        is True
    )
    assert cx_processing_api_smoke._failed_error_hash_projected({"steps": []}) is False
    assert (
        cx_processing_api_smoke._failed_error_hash_projected(
            {
                "steps": [
                    {
                        "error_detail_sha256": cx_processing_api_smoke._sha256_text(
                            cx_processing_api_smoke.SECRET_ERROR_DETAIL
                        )
                    }
                ]
            }
        )
        is True
    )


def test_cx_processing_postgres_api_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cx_processing_api_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        cx_processing_api_smoke,
        "run_cx_processing_postgres_api_smoke",
        lambda: {
            "smoke_schema_version": "cx_processing_postgres_api_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_CX_PROCESSING_POSTGRES_API_SMOKE is not enabled.",
        },
    )

    assert cx_processing_api_smoke.main(["--summary"]) == 0
    assert "cx_processing_postgres_api_smoke=skipped" in capsys.readouterr().out

    assert cx_processing_api_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_cx_upload_ownership_postgres_smoke_skips_by_default() -> None:
    evidence = cx_upload_ownership_smoke.run_cx_upload_ownership_postgres_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert cx_upload_ownership_smoke.summary_line(evidence) == (
        "cx_upload_ownership_postgres_smoke=skipped "
        "reason=NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE"
    )


def test_cx_upload_ownership_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = cx_upload_ownership_smoke.run_cx_upload_ownership_postgres_smoke(
        environ={
            "NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE": "1",
            "NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_cx_upload_ownership_postgres_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append(
            (service_id, profile)
        ),
    )
    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "_execute_upload_ownership_smoke",
        lambda database_url, runtime_environ: {
            "document_id": "doc-001",
            "source_file_id": "source-001",
            "checks": {
                "api_status_created": True,
                "runtime_mode": True,
                "resolver_called_once": True,
                "resolver_verify_only": True,
                "persisted_content_owner_refs": True,
                "persisted_owner_acl_ref": True,
                "source_checksum_verified": True,
                "source_file_path_materialized": True,
                "raw_payload_absent": True,
            },
        },
    )

    evidence = cx_upload_ownership_smoke.run_cx_upload_ownership_postgres_smoke(
        environ={"NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["checks"]["persisted_content_owner_refs"] is True
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert cx_upload_ownership_smoke.summary_line(evidence) == (
        "cx_upload_ownership_postgres_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env"
    )


def test_cx_upload_ownership_postgres_smoke_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise cx_upload_ownership_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = cx_upload_ownership_smoke.run_cx_upload_ownership_postgres_smoke(
        environ={"NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "_execute_upload_ownership_smoke",
        raise_runtime_error,
    )
    execution_failure = cx_upload_ownership_smoke.run_cx_upload_ownership_postgres_smoke(
        environ={"NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert cx_upload_ownership_smoke.summary_line(execution_failure) == (
        "cx_upload_ownership_postgres_smoke=fail "
        "service=nex-cx reason=execution_failed"
    )


def test_cx_upload_ownership_postgres_smoke_execute_with_sqlite_fixture(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-upload-ownership.sqlite'}"
    engine = cx_upload_ownership_smoke.build_engine(database_url)
    _create_sqlite_cx_content_retrieval_tables(engine)

    evidence = cx_upload_ownership_smoke._execute_upload_ownership_smoke(
        database_url=database_url,
        runtime_environ={
            "NEX_CX_DATABASE_URL": database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
            "NEX_CX_UPLOAD_OWNER_RESOLVER_MODE": "verify",
        },
    )

    assert evidence["checks"] == {
        "api_status_created": True,
        "runtime_mode": True,
        "resolver_called_once": True,
        "resolver_verify_only": True,
        "persisted_content_owner_refs": True,
        "persisted_owner_acl_ref": True,
        "source_checksum_verified": True,
        "source_file_path_materialized": True,
        "raw_payload_absent": True,
    }
    with engine.begin() as connection:
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_content == 0
    assert remaining_sources == 0


def test_cx_upload_ownership_postgres_smoke_execute_failure_edges(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-upload-ownership-edge.sqlite'}"
    engine = cx_upload_ownership_smoke.build_engine(database_url)
    _create_sqlite_cx_content_retrieval_tables(engine)

    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(api_session_factory=None),
    )
    with pytest.raises(RuntimeError, match="session factory"):
        cx_upload_ownership_smoke._execute_upload_ownership_smoke(
            database_url=database_url,
            runtime_environ={
                "NEX_CX_DATABASE_URL": database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )

    monkeypatch.undo()
    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "_content_owner_refs_match",
        lambda stored, ownership_ref: False,
    )
    with pytest.raises(RuntimeError, match="smoke checks failed"):
        cx_upload_ownership_smoke._execute_upload_ownership_smoke(
            database_url=database_url,
            runtime_environ={
                "NEX_CX_DATABASE_URL": database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )

    with engine.begin() as connection:
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_content == 0
    assert remaining_sources == 0


def test_cx_upload_ownership_postgres_smoke_helpers_cover_edges() -> None:
    ownership_ref = cx_upload_ownership_smoke._ownership_ref(
        "aabbccdd-0000-0000-0000-000000000000"
    )
    matching = {
        "tenant_ref_type": "oa.tenant",
        "tenant_ref_id": "tenant-smoke-aabbccdd",
        "owner_subject_ref_type": "oa.user",
        "owner_subject_ref_id": "owner-smoke-aabbccdd",
        "uploaded_by_subject_ref_type": "oa.user",
        "uploaded_by_subject_ref_id": "uploader-smoke-aabbccdd",
        "principal_ref_type": "oa.user",
        "principal_ref_id": "owner-smoke-aabbccdd",
        "granted_by_subject_ref_type": "oa.user",
        "granted_by_subject_ref_id": "uploader-smoke-aabbccdd",
    }

    assert cx_upload_ownership_smoke._content_owner_refs_match(
        matching,
        ownership_ref,
    )
    assert cx_upload_ownership_smoke._owner_acl_ref_matches(matching, ownership_ref)
    assert not cx_upload_ownership_smoke._content_owner_refs_match(
        {**matching, "owner_subject_ref_id": "other"},
        ownership_ref,
    )
    assert not cx_upload_ownership_smoke._owner_acl_ref_matches(
        {**matching, "principal_ref_id": "other"},
        ownership_ref,
    )


def test_cx_upload_ownership_postgres_smoke_db_helper_edges(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-upload-helper.sqlite'}"
    engine = cx_upload_ownership_smoke.build_engine(database_url)
    _create_sqlite_cx_content_retrieval_tables(engine)

    with pytest.raises(RuntimeError, match="was not persisted"):
        cx_upload_ownership_smoke._read_stored_upload_ownership(
            engine,
            document_id="00000000-0000-0000-0000-000000000000",
        )

    cx_upload_ownership_smoke._delete_smoke_upload_rows(
        engine,
        document_id=None,
        source_file_id=None,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO cx_source_files (
                    source_file_id,
                    source_sha256,
                    size_bytes,
                    content_type,
                    storage_uri,
                    storage_backend,
                    storage_key,
                    stored_filename,
                    stored_extension,
                    created_at
                )
                VALUES (
                    'source-helper',
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                    1,
                    'text/plain',
                    'local://cx/source-files/20260810/aa/aa/source-helper.txt',
                    'local_filesystem',
                    '20260810/aa/aa/source-helper.txt',
                    'source-helper.txt',
                    '.txt',
                    '2026-08-10T00:00:00Z'
                )
                """
            )
        )
    cx_upload_ownership_smoke._delete_smoke_upload_rows(
        engine,
        document_id=None,
        source_file_id="source-helper",
    )
    with engine.begin() as connection:
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_sources == 0


def test_cx_upload_ownership_postgres_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cx_upload_ownership_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        cx_upload_ownership_smoke,
        "run_cx_upload_ownership_postgres_smoke",
        lambda: {
            "smoke_schema_version": "cx_upload_ownership_postgres_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE is not enabled.",
        },
    )

    assert cx_upload_ownership_smoke.main(["--summary"]) == 0
    assert "cx_upload_ownership_postgres_smoke=skipped" in capsys.readouterr().out

    assert cx_upload_ownership_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_cx_upload_duplicate_postgres_smoke_skips_by_default() -> None:
    evidence = cx_upload_duplicate_smoke.run_cx_upload_duplicate_postgres_smoke(
        environ={}
    )

    assert evidence["status"] == "SKIPPED"
    assert cx_upload_duplicate_smoke.summary_line(evidence) == (
        "cx_upload_duplicate_postgres_smoke=skipped "
        "reason=NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE"
    )


def test_cx_upload_duplicate_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = cx_upload_duplicate_smoke.run_cx_upload_duplicate_postgres_smoke(
        environ={
            "NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE": "1",
            "NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_cx_upload_duplicate_postgres_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append(
            (service_id, profile)
        ),
    )
    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "_execute_upload_duplicate_smoke",
        lambda database_url, runtime_environ: {
            "document_id": "doc-001",
            "duplicate_document_id": "doc-001",
            "other_owner_document_id": "doc-002",
            "source_file_id": "source-001",
            "source_sha256": "a" * 64,
            "checks": {
                "runtime_mode": True,
                "first_upload_created": True,
                "duplicate_upload_reused": True,
                "duplicate_document_id_reused": True,
                "duplicate_existing_document_reported": True,
                "other_owner_created": True,
                "other_owner_document_distinct": True,
                "source_file_reused_across_owners": True,
                "same_owner_active_content_count": True,
                "other_owner_active_content_count": True,
                "source_file_count": True,
                "active_content_count": True,
                "owner_acl_count": True,
                "raw_payload_absent": True,
            },
        },
    )

    evidence = cx_upload_duplicate_smoke.run_cx_upload_duplicate_postgres_smoke(
        environ={"NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["checks"]["duplicate_upload_reused"] is True
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert cx_upload_duplicate_smoke.summary_line(evidence) == (
        "cx_upload_duplicate_postgres_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env"
    )


def test_cx_upload_duplicate_postgres_smoke_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise cx_upload_duplicate_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = cx_upload_duplicate_smoke.run_cx_upload_duplicate_postgres_smoke(
        environ={"NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "_execute_upload_duplicate_smoke",
        raise_runtime_error,
    )
    execution_failure = cx_upload_duplicate_smoke.run_cx_upload_duplicate_postgres_smoke(
        environ={"NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert cx_upload_duplicate_smoke.summary_line(execution_failure) == (
        "cx_upload_duplicate_postgres_smoke=fail "
        "service=nex-cx reason=execution_failed"
    )


def test_cx_upload_duplicate_postgres_smoke_execute_with_sqlite_fixture(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-upload-duplicate.sqlite'}"
    engine = cx_upload_duplicate_smoke.build_engine(database_url)
    _create_sqlite_cx_content_retrieval_tables(engine)

    evidence = cx_upload_duplicate_smoke._execute_upload_duplicate_smoke(
        database_url=database_url,
        runtime_environ={
            cx_upload_duplicate_smoke.SERVICE_SPEC.database_env: database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
        },
    )

    assert evidence["document_id"] == evidence["duplicate_document_id"]
    assert evidence["other_owner_document_id"] != evidence["document_id"]
    assert evidence["checks"] == {
        "runtime_mode": True,
        "first_upload_created": True,
        "duplicate_upload_reused": True,
        "duplicate_document_id_reused": True,
        "duplicate_existing_document_reported": True,
        "other_owner_created": True,
        "other_owner_document_distinct": True,
        "source_file_reused_across_owners": True,
        "same_owner_active_content_count": True,
        "other_owner_active_content_count": True,
        "source_file_count": True,
        "active_content_count": True,
        "owner_acl_count": True,
        "raw_payload_absent": True,
    }
    with engine.begin() as connection:
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_content == 0
    assert remaining_sources == 0


def test_cx_upload_duplicate_postgres_smoke_execute_failure_edges(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-upload-duplicate-edge.sqlite'}"
    engine = cx_upload_duplicate_smoke.build_engine(database_url)
    _create_sqlite_cx_content_retrieval_tables(engine)

    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(api_session_factory=None),
    )
    with pytest.raises(RuntimeError, match="session factory"):
        cx_upload_duplicate_smoke._execute_upload_duplicate_smoke(
            database_url=database_url,
            runtime_environ={
                cx_upload_duplicate_smoke.SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )

    monkeypatch.undo()
    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "_count_active_source_documents",
        lambda *args, **kwargs: 3,
    )
    with pytest.raises(RuntimeError, match="smoke checks failed"):
        cx_upload_duplicate_smoke._execute_upload_duplicate_smoke(
            database_url=database_url,
            runtime_environ={
                cx_upload_duplicate_smoke.SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )

    with engine.begin() as connection:
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_content == 0
    assert remaining_sources == 0


def test_cx_upload_duplicate_postgres_smoke_cleanup_and_main_edges(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-upload-duplicate-helper.sqlite'}"
    engine = cx_upload_duplicate_smoke.build_engine(database_url)
    _create_sqlite_cx_content_retrieval_tables(engine)

    assert cx_upload_duplicate_smoke._unique_present_values(
        [None, "doc-a", "doc-a", "doc-b"]
    ) == ["doc-a", "doc-b"]
    cx_upload_duplicate_smoke._delete_upload_duplicate_smoke_rows(
        engine,
        document_ids=[None, "missing", "missing"],
        source_file_ids=[None, "missing-source", "missing-source"],
    )

    monkeypatch.setattr(cx_upload_duplicate_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        cx_upload_duplicate_smoke,
        "run_cx_upload_duplicate_postgres_smoke",
        lambda: {
            "smoke_schema_version": "cx_upload_duplicate_postgres_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE is not enabled.",
        },
    )

    assert cx_upload_duplicate_smoke.main(["--summary"]) == 0
    assert "cx_upload_duplicate_postgres_smoke=skipped" in capsys.readouterr().out

    assert cx_upload_duplicate_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_cx_document_library_postgres_smoke_skips_by_default() -> None:
    evidence = cx_document_library_smoke.run_cx_document_library_postgres_smoke(
        environ={}
    )

    assert evidence["status"] == "SKIPPED"
    assert cx_document_library_smoke.summary_line(evidence) == (
        "cx_document_library_postgres_smoke=skipped "
        "reason=NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE"
    )


def test_cx_document_library_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = cx_document_library_smoke.run_cx_document_library_postgres_smoke(
        environ={
            "NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE": "1",
            "NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_cx_document_library_postgres_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        cx_document_library_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        cx_document_library_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_document_library_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: (
            migration_calls.append((service_id, profile))
            or SimpleNamespace(
                service_id=service_id,
                profile=profile,
                planned=("001", "002"),
                applied=(),
                skipped=("001", "002"),
                dry_run=False,
            )
        ),
    )
    monkeypatch.setattr(
        cx_document_library_smoke,
        "_execute_document_library_smoke",
        lambda database_env, database_url, runtime_environ: {
            "document_id": "doc-001",
            "other_owner_document_id": "doc-002",
            "returned_count": 1,
            "checks": {
                "runtime_mode": True,
                "api_upload_status_created": True,
                "list_status_ok": True,
                "source_metadata_uses_test_db": True,
                "projection_schema_version": True,
                "owner_scope_filtered": True,
                "other_owner_excluded": True,
                "persisted_owner_a_count": True,
                "persisted_owner_b_count": True,
                "raw_payload_absent": True,
            },
        },
    )

    evidence = cx_document_library_smoke.run_cx_document_library_postgres_smoke(
        environ={"NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["checks"]["owner_scope_filtered"] is True
    assert evidence["migration"] == {
        "service_id": "nex-cx",
        "profile": "test",
        "planned_count": 2,
        "applied_count": 0,
        "skipped_count": 2,
        "dry_run": False,
    }
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert cx_document_library_smoke.summary_line(evidence) == (
        "cx_document_library_postgres_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env"
    )


def test_cx_document_library_postgres_smoke_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise cx_document_library_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        cx_document_library_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = cx_document_library_smoke.run_cx_document_library_postgres_smoke(
        environ={"NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        cx_document_library_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        cx_document_library_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        cx_document_library_smoke,
        "_execute_document_library_smoke",
        raise_runtime_error,
    )
    execution_failure = cx_document_library_smoke.run_cx_document_library_postgres_smoke(
        environ={"NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert cx_document_library_smoke.summary_line(execution_failure) == (
        "cx_document_library_postgres_smoke=fail "
        "service=nex-cx reason=execution_failed"
    )


def test_cx_document_library_postgres_smoke_execute_with_sqlite_fixture(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-document-library.sqlite'}"
    engine = cx_document_library_smoke.build_engine(database_url)
    _create_sqlite_cx_document_library_tables(engine)

    evidence = cx_document_library_smoke._execute_document_library_smoke(
        database_env="NEX_CX_TEST_DATABASE_URL",
        database_url=database_url,
        runtime_environ={
            cx_document_library_smoke.SERVICE_SPEC.database_env: database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
        },
    )

    assert evidence["returned_count"] == 1
    assert evidence["db_observations"] == {
        "owner_a_active_content_count": 1,
        "owner_b_active_content_count": 1,
        "listed_document_count": 1,
        "listed_document_ids": [evidence["document_id"]],
    }
    assert evidence["cleanup_observations"] == [
        {
            "label": "owner_a",
            "document_id": evidence["document_id"],
            "source_file_id": evidence["cleanup_observations"][0]["source_file_id"],
            "content_rows_before_delete": 1,
            "source_rows_before_delete": 1,
            "content_rows_after_delete": 0,
            "source_rows_after_delete": 0,
        },
        {
            "label": "owner_b",
            "document_id": evidence["other_owner_document_id"],
            "source_file_id": evidence["cleanup_observations"][1]["source_file_id"],
            "content_rows_before_delete": 1,
            "source_rows_before_delete": 1,
            "content_rows_after_delete": 0,
            "source_rows_after_delete": 0,
        },
    ]
    assert evidence["checks"] == {
        "runtime_mode": True,
        "api_upload_status_created": True,
        "list_status_ok": True,
        "source_metadata_uses_test_db": True,
        "projection_schema_version": True,
        "owner_scope_filtered": True,
        "other_owner_excluded": True,
        "persisted_owner_a_count": True,
        "persisted_owner_b_count": True,
        "raw_payload_absent": True,
    }
    with engine.begin() as connection:
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_content == 0
    assert remaining_sources == 0


def test_cx_document_library_postgres_smoke_observation_helpers(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-document-library-helper.sqlite'}"
    engine = cx_document_library_smoke.build_engine(database_url)
    _create_sqlite_cx_document_library_tables(engine)

    assert (
        cx_document_library_smoke._count_content_object_by_id(
            engine,
            document_id=None,
        )
        == 0
    )
    assert (
        cx_document_library_smoke._count_source_file_by_id(
            engine,
            source_file_id=None,
        )
        == 0
    )
    assert cx_document_library_smoke._migration_evidence(
        SimpleNamespace(
            service_id="nex-cx",
            profile="test",
            planned=("001",),
            applied=("001",),
            skipped=(),
            dry_run=True,
        )
    ) == {
        "service_id": "nex-cx",
        "profile": "test",
        "planned_count": 1,
        "applied_count": 1,
        "skipped_count": 0,
        "dry_run": True,
    }
    assert cx_document_library_smoke._migration_evidence(object()) == {
        "service_id": "nex-cx",
        "profile": "test",
        "planned_count": 0,
        "applied_count": 0,
        "skipped_count": 0,
        "dry_run": False,
    }
    assert cx_document_library_smoke._delete_document_library_smoke_rows(
        engine,
        entries=[
            {"label": "missing", "document_id": None, "source_file_id": None},
        ],
    ) == [
        {
            "label": "missing",
            "document_id": None,
            "source_file_id": None,
            "content_rows_before_delete": 0,
            "source_rows_before_delete": 0,
            "content_rows_after_delete": 0,
            "source_rows_after_delete": 0,
        }
    ]


def test_cx_document_library_postgres_smoke_execute_failure_edges(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-document-library-edge.sqlite'}"
    engine = cx_document_library_smoke.build_engine(database_url)
    _create_sqlite_cx_document_library_tables(engine)

    monkeypatch.setattr(
        cx_document_library_smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(api_session_factory=None),
    )
    with pytest.raises(RuntimeError, match="session factory"):
        cx_document_library_smoke._execute_document_library_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                cx_document_library_smoke.SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )

    monkeypatch.undo()
    monkeypatch.setattr(
        cx_document_library_smoke,
        "_count_active_owner_documents",
        lambda *args, **kwargs: 0,
    )
    with pytest.raises(RuntimeError, match="smoke checks failed"):
        cx_document_library_smoke._execute_document_library_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                cx_document_library_smoke.SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )

    with engine.begin() as connection:
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_content == 0
    assert remaining_sources == 0


def test_cx_document_library_postgres_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cx_document_library_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        cx_document_library_smoke,
        "run_cx_document_library_postgres_smoke",
        lambda: {
            "smoke_schema_version": "cx_document_library_postgres_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE is not enabled.",
        },
    )

    assert cx_document_library_smoke.main(["--summary"]) == 0
    assert "cx_document_library_postgres_smoke=skipped" in capsys.readouterr().out

    assert cx_document_library_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_ag_cx_processing_run_postgres_smoke_skips_by_default() -> None:
    evidence = ag_cx_processing_smoke.run_ag_cx_processing_run_postgres_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert ag_cx_processing_smoke.summary_line(evidence) == (
        "ag_cx_processing_run_postgres_smoke=skipped "
        "reason=NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE"
    )


def test_ag_cx_processing_run_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = ag_cx_processing_smoke.run_ag_cx_processing_run_postgres_smoke(
        environ={
            "NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE": "1",
            "NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_ag_cx_processing_run_postgres_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        ag_cx_processing_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        ag_cx_processing_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        ag_cx_processing_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append(
            (service_id, profile)
        ),
    )
    monkeypatch.setattr(
        ag_cx_processing_smoke,
        "_execute_ag_cx_processing_run_postgres_smoke",
        lambda database_url, database_env, environ: {
            "pipeline_run_id": "pipeline-001",
            "request_id": "request-001",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "projection_versions": {
                "list": "ag_cx_processing_run_operations_projection.v1",
                "detail": "ag_cx_processing_run_detail_projection.v1",
            },
            "http_statuses": {"list": 200, "detail": 200},
            "counts": {
                "list_total": 1,
                "detail_steps": 2,
                "detail_error_hashes": 1,
            },
            "checks": {"ok": True},
        },
    )

    evidence = ag_cx_processing_smoke.run_ag_cx_processing_run_postgres_smoke(
        environ={"NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert ag_cx_processing_smoke.summary_line(evidence) == (
        "ag_cx_processing_run_postgres_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env "
        "list=1 detail_steps=2 error_hashes=1"
    )


def test_ag_cx_processing_run_postgres_smoke_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise ag_cx_processing_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        ag_cx_processing_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = ag_cx_processing_smoke.run_ag_cx_processing_run_postgres_smoke(
        environ={"NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        ag_cx_processing_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        ag_cx_processing_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        ag_cx_processing_smoke,
        "_execute_ag_cx_processing_run_postgres_smoke",
        raise_runtime_error,
    )
    execution_failure = ag_cx_processing_smoke.run_ag_cx_processing_run_postgres_smoke(
        environ={"NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert ag_cx_processing_smoke.summary_line(execution_failure) == (
        "ag_cx_processing_run_postgres_smoke=fail "
        "service=nex-cx reason=execution_failed"
    )


def test_ag_cx_processing_run_postgres_smoke_execute_with_sqlite_fixture(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'ag-cx-processing-smoke.sqlite'}"
    engine = ag_cx_processing_smoke.build_engine(database_url)
    _create_sqlite_cx_processing_persistence_tables(engine)

    evidence = ag_cx_processing_smoke._execute_ag_cx_processing_run_postgres_smoke(
        database_url=database_url,
        database_env="NEX_CX_TEST_DATABASE_URL",
        environ={},
    )

    assert evidence["checks"] == {
        "list_projection_reads_postgres": True,
        "list_filter_returns_seeded_run": True,
        "detail_projection_includes_safe_steps": True,
        "detail_source_status_ready": True,
        "raw_values_absent_from_ag_evidence": True,
    }
    assert evidence["counts"] == {
        "list_total": 1,
        "detail_steps": 2,
        "detail_error_hashes": 1,
    }
    with engine.begin() as connection:
        remaining_runs = connection.execute(
            text("SELECT count(*) FROM cx_document_processing_runs")
        ).scalar_one()
        remaining_steps = connection.execute(
            text("SELECT count(*) FROM cx_document_processing_steps")
        ).scalar_one()
        remaining_content = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        remaining_sources = connection.execute(
            text("SELECT count(*) FROM cx_source_files")
        ).scalar_one()
    assert remaining_runs == 0
    assert remaining_steps == 0
    assert remaining_content == 0
    assert remaining_sources == 0


def test_ag_cx_processing_run_postgres_smoke_helpers_cover_edges() -> None:
    refs = ag_cx_processing_smoke._smoke_refs()
    checks = ag_cx_processing_smoke._checks(
        list_response={
            "_http_status": 500,
            "processing_runs": [],
            "summary": {},
        },
        detail_response={
            "_http_status": 404,
            "processing_run": {"steps": []},
            "summary": {},
        },
        refs=refs,
        raw_values=[refs["source_text"]],
    )

    assert checks == {
        "list_projection_reads_postgres": False,
        "list_filter_returns_seeded_run": False,
        "detail_projection_includes_safe_steps": False,
        "detail_source_status_ready": False,
        "raw_values_absent_from_ag_evidence": True,
    }
    assert ag_cx_processing_smoke._json_sql_expression(
        SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        "payload",
    ) == "CAST(:payload AS jsonb)"
    assert ag_cx_processing_smoke._redaction_safe(
        {"safe": "value"},
        [refs["source_text"]],
    )
    assert not ag_cx_processing_smoke._redaction_safe(
        {"leak": refs["source_text"]},
        [refs["source_text"]],
    )


def test_ag_cx_processing_run_postgres_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(ag_cx_processing_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        ag_cx_processing_smoke,
        "run_ag_cx_processing_run_postgres_smoke",
        lambda: {
            "smoke_schema_version": "ag_cx_processing_run_postgres_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE is not enabled.",
        },
    )

    assert ag_cx_processing_smoke.main(["--summary"]) == 0
    assert "ag_cx_processing_run_postgres_smoke=skipped" in capsys.readouterr().out

    assert ag_cx_processing_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_ag_cross_service_observability_smoke_skips_by_default() -> None:
    evidence = ag_observability_smoke.run_ag_cross_service_observability_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert ag_observability_smoke.summary_line(evidence) == (
        "ag_cross_service_observability_smoke=skipped "
        "reason=NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE"
    )


def test_ag_cross_service_observability_smoke_rejects_non_test_profile() -> None:
    evidence = ag_observability_smoke.run_ag_cross_service_observability_smoke(
        environ={
            "NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE": "1",
            "NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_ag_cross_service_observability_smoke_reports_pass_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []
    runtime_environ_seen: dict[str, str] = {}

    monkeypatch.setattr(
        ag_observability_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        ag_observability_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        ag_observability_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: migration_calls.append(
            (service_id, profile)
        ),
    )

    def fake_execute(database_url: str, runtime_environ: dict[str, str]) -> dict[str, object]:
        runtime_environ_seen.update(runtime_environ)
        return {
            "pipeline_run_id": "pipeline-001",
            "document_id": "doc-001",
            "job_id": "job-001",
            "event_ids": ["event-started", "event-succeeded"],
            "checks": {
                "cx_runtime_mode": True,
                "ag_source_runtime_mode": True,
                "ag_source_runtime_profile": True,
                "ag_source_registry_present": True,
                "ag_source_kind": True,
                "projection_ready": True,
                "job_visible": True,
                "started_event_visible": True,
                "succeeded_event_visible": True,
                "event_trace_filter": True,
                "redaction_safe": True,
            },
        }

    monkeypatch.setattr(
        ag_observability_smoke,
        "_execute_cross_service_observability_smoke",
        fake_execute,
    )

    evidence = ag_observability_smoke.run_ag_cross_service_observability_smoke(
        environ={"NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-cx:test:env"
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert evidence["checks"]["job_visible"] is True
    assert "secret" not in str(evidence)
    assert migration_calls == [("nex-cx", "test")]
    assert runtime_environ_seen["NEX_CX_PERSISTENCE_MODE"] == "postgres"
    assert runtime_environ_seen["NEX_AG_OPERATIONS_SOURCE_MODE"] == "postgres"
    assert runtime_environ_seen["NEX_AG_OPERATIONS_SOURCE_PROFILE"] == "test"
    assert runtime_environ_seen["NEX_AG_OPERATIONS_SOURCE_SERVICES"] == "nex-cx"
    assert ag_observability_smoke.summary_line(evidence) == (
        "ag_cross_service_observability_smoke=pass "
        "service=nex-cx db_env=nex-cx:test:env job=job-001 events=2"
    )


def test_ag_cross_service_observability_smoke_reports_config_and_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise ag_observability_smoke.MigrationError("missing database URL env")

    monkeypatch.setattr(
        ag_observability_smoke,
        "service_database_url",
        raise_migration_error,
    )
    config_failure = ag_observability_smoke.run_ag_cross_service_observability_smoke(
        environ={"NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        ag_observability_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        ag_observability_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: None,
    )

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        ag_observability_smoke,
        "_execute_cross_service_observability_smoke",
        raise_runtime_error,
    )
    execution_failure = ag_observability_smoke.run_ag_cross_service_observability_smoke(
        environ={"NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert ag_observability_smoke.summary_line(execution_failure) == (
        "ag_cross_service_observability_smoke=fail service=nex-cx reason=execution_failed"
    )


def test_ag_cross_service_observability_smoke_execute_with_sqlite_fixture(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'ag-observability-smoke.sqlite'}"
    engine = ag_observability_smoke.build_engine(database_url)
    _create_sqlite_service_jobs_table(engine)
    _create_sqlite_service_operational_events_table(engine)
    _create_sqlite_service_worker_heartbeats_table(engine)

    evidence = ag_observability_smoke._execute_cross_service_observability_smoke(
        database_url=database_url,
        runtime_environ={
            "NEX_CX_DATABASE_URL": database_url,
            "NEX_CX_TEST_DATABASE_URL": database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
            "NEX_AG_OPERATIONS_SOURCE_MODE": "postgres",
            "NEX_AG_OPERATIONS_SOURCE_PROFILE": "test",
            "NEX_AG_OPERATIONS_SOURCE_SERVICES": "nex-cx",
        },
    )

    assert evidence["checks"] == {
        "cx_runtime_mode": True,
        "ag_source_runtime_mode": True,
        "ag_source_runtime_profile": True,
        "ag_source_registry_present": True,
        "ag_source_kind": True,
        "projection_ready": True,
        "job_visible": True,
        "started_event_visible": True,
        "succeeded_event_visible": True,
        "worker_busy_event_visible": True,
        "worker_idle_event_visible": True,
        "event_trace_filter": True,
        "redaction_safe": True,
    }
    assert len(evidence["event_ids"]) == 4
    with engine.begin() as connection:
        remaining_jobs = connection.execute(text("SELECT count(*) FROM service_jobs")).scalar_one()
        remaining_events = connection.execute(
            text("SELECT count(*) FROM service_operational_events")
        ).scalar_one()
        remaining_heartbeats = connection.execute(
            text("SELECT count(*) FROM service_worker_heartbeats")
        ).scalar_one()
    assert remaining_jobs == 0
    assert remaining_events == 0
    assert remaining_heartbeats == 0


def test_ag_cross_service_observability_smoke_projection_helpers_cover_edges() -> None:
    projection = {
        "projection_status": "READY",
        "jobs": {
            "jobs": [
                {
                    "job_id": "job-001",
                    "status": "SUCCEEDED",
                }
            ]
        },
        "events": {
            "events": [
                {
                    "event_id": "event-started",
                    "event_type": ag_observability_smoke.PROCESSING_EVENT_STARTED,
                    "trace_id": "trace-001",
                },
                {
                    "event_id": "event-succeeded",
                    "event_type": ag_observability_smoke.PROCESSING_EVENT_SUCCEEDED,
                    "trace_id": "trace-001",
                },
                {
                    "event_id": "event-worker-busy",
                    "event_type": ag_observability_smoke.PROCESSING_WORKER_EVENT_BUSY,
                    "trace_id": "trace-001",
                },
                {
                    "event_id": "event-worker-idle",
                    "event_type": ag_observability_smoke.PROCESSING_WORKER_EVENT_IDLE,
                    "trace_id": "trace-001",
                },
            ]
        },
        "source_registry": {
            "service_count": 1,
            "sources": {
                "nex-cx": {
                    "source_kind": "postgres-read",
                }
            },
        },
        "ag_source_runtime": {
            "mode": "postgres",
            "profile": "test",
        },
    }

    checks = ag_observability_smoke._cross_service_observability_checks(
        cx_runtime_mode="postgres",
        ag_projection=projection,
        job_id="job-001",
        trace_id="trace-001",
    )
    assert all(checks.values())
    assert ag_observability_smoke._projected_event_ids(projection) == [
        "event-started",
        "event-succeeded",
        "event-worker-busy",
        "event-worker-idle",
    ]
    assert ag_observability_smoke._projected_jobs({"jobs": []}) == []
    assert ag_observability_smoke._projected_events({"events": []}) == []
    assert "Authorization" in ag_observability_smoke._ag_service_headers(
        trace_id="0" * 32
    )

    degraded_projection = {
        **projection,
        "projection_status": "DEGRADED",
        "events": {"events": [{"event_type": "other", "trace_id": "wrong"}]},
        "source_registry": {"service_count": 0, "sources": {}},
        "ag_source_runtime": {"mode": "memory", "profile": "dev"},
        "unsafe": "secret",
    }
    degraded_checks = ag_observability_smoke._cross_service_observability_checks(
        cx_runtime_mode="memory",
        ag_projection=degraded_projection,
        job_id="missing",
        trace_id="trace-001",
    )
    assert degraded_checks["cx_runtime_mode"] is False
    assert degraded_checks["projection_ready"] is False
    assert degraded_checks["redaction_safe"] is False


def test_ag_cross_service_observability_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(ag_observability_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        ag_observability_smoke,
        "run_ag_cross_service_observability_smoke",
        lambda: {
            "smoke_schema_version": "ag_cross_service_observability_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE is not enabled.",
        },
    )

    assert ag_observability_smoke.main(["--summary"]) == 0
    assert "ag_cross_service_observability_smoke=skipped" in capsys.readouterr().out

    assert ag_observability_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def _create_sqlite_cx_document_library_tables(engine: object) -> None:
    _create_sqlite_cx_content_retrieval_tables(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_summaries (
                    document_summary_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    extraction_artifact_id TEXT NOT NULL REFERENCES cx_extraction_artifacts(extraction_artifact_id),
                    prompt_template_version_id TEXT,
                    summary_chunk_policy_id TEXT NOT NULL,
                    summary_text_sha256 TEXT NOT NULL,
                    summary_storage_uri TEXT NOT NULL,
                    summary_char_count INTEGER NOT NULL,
                    summary_max_chars INTEGER NOT NULL,
                    summary_hard_limit_chars INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    language_code TEXT NOT NULL,
                    model_profile_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_summary_embeddings (
                    summary_embedding_id TEXT PRIMARY KEY,
                    document_summary_id TEXT NOT NULL REFERENCES cx_document_summaries(document_summary_id),
                    provider_alias TEXT NOT NULL,
                    model_profile_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    deployment_id TEXT NOT NULL,
                    vector_dimension INTEGER NOT NULL,
                    embedding_sha256 TEXT NOT NULL,
                    embedding_storage_uri TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_processing_runs (
                    pipeline_run_id TEXT PRIMARY KEY,
                    pipeline_schema_version TEXT NOT NULL DEFAULT 'cx_document_processing_pipeline.v1',
                    document_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    status TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT NOT NULL,
                    job_id TEXT,
                    job_type TEXT,
                    job_status TEXT,
                    job_attempt_count INTEGER NOT NULL DEFAULT 0,
                    job_max_attempts INTEGER NOT NULL DEFAULT 0,
                    job_retryable BOOLEAN,
                    job_subject_ref TEXT NOT NULL DEFAULT '{}',
                    job_links TEXT NOT NULL DEFAULT '{}',
                    step_total INTEGER NOT NULL DEFAULT 0,
                    step_succeeded INTEGER NOT NULL DEFAULT 0,
                    step_skipped INTEGER NOT NULL DEFAULT 0,
                    step_failed INTEGER NOT NULL DEFAULT 0,
                    queued_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_processing_steps (
                    pipeline_run_id TEXT NOT NULL REFERENCES cx_document_processing_runs(pipeline_run_id),
                    step_order INTEGER NOT NULL,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_ref_type TEXT,
                    output_ref_id TEXT,
                    output_ref_document_id TEXT REFERENCES cx_content_objects(content_object_id),
                    output_ref_hash TEXT,
                    error_code TEXT,
                    error_detail_sha256 TEXT,
                    error_retryable BOOLEAN,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (pipeline_run_id, step_order),
                    UNIQUE (pipeline_run_id, step_id)
                )
                """
            )
        )


def _create_sqlite_cx_content_retrieval_tables(engine: object) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_source_files (
                    source_file_id TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    storage_uri TEXT NOT NULL,
                    first_seen_trace_id TEXT,
                    storage_backend TEXT NOT NULL DEFAULT 'local_filesystem',
                    storage_key TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    stored_extension TEXT NOT NULL,
                    checksum_verified_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_objects (
                    content_object_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    tenant_ref_type TEXT NOT NULL DEFAULT 'oa.tenant',
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_type TEXT NOT NULL DEFAULT 'oa.user',
                    owner_subject_ref_id TEXT NOT NULL,
                    uploaded_by_subject_ref_type TEXT NOT NULL DEFAULT 'oa.user',
                    uploaded_by_subject_ref_id TEXT NOT NULL,
                    source_file_id TEXT NOT NULL REFERENCES cx_source_files(source_file_id),
                    source_sha256 TEXT NOT NULL,
                    upload_id TEXT NOT NULL UNIQUE,
                    original_filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    classification TEXT NOT NULL DEFAULT 'internal',
                    lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
                    retrieval_policy TEXT NOT NULL DEFAULT '{}',
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (tenant_id, owner_user_id, source_sha256)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX ux_cx_content_owner_subject_source_active
                ON cx_content_objects (
                    tenant_ref_type,
                    tenant_ref_id,
                    owner_subject_ref_type,
                    owner_subject_ref_id,
                    source_sha256
                )
                WHERE lifecycle_status = 'ACTIVE'
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_acl_entries (
                    acl_entry_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    principal_type TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    principal_ref_type TEXT NOT NULL,
                    principal_ref_id TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    granted_by_user_id TEXT,
                    granted_by_subject_ref_type TEXT,
                    granted_by_subject_ref_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (content_object_id, principal_type, principal_id, permission)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX ux_cx_content_acl_subject_ref_permission
                ON cx_content_acl_entries (
                    content_object_id,
                    principal_ref_type,
                    principal_ref_id,
                    permission
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_extraction_artifacts (
                    extraction_artifact_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    source_file_id TEXT NOT NULL REFERENCES cx_source_files(source_file_id),
                    artifact_kind TEXT NOT NULL DEFAULT 'markdown',
                    status TEXT NOT NULL DEFAULT 'SUCCEEDED',
                    extractor_name TEXT NOT NULL,
                    extractor_version TEXT NOT NULL,
                    markdown_sha256 TEXT NOT NULL,
                    markdown_storage_uri TEXT NOT NULL,
                    markdown_char_count INTEGER NOT NULL,
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (
                        content_object_id,
                        extractor_name,
                        extractor_version,
                        markdown_sha256
                    )
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_chunk_sets (
                    chunk_set_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    extraction_artifact_id TEXT NOT NULL REFERENCES cx_extraction_artifacts(extraction_artifact_id),
                    chunk_policy_id TEXT NOT NULL,
                    chunk_size INTEGER NOT NULL,
                    chunk_overlap INTEGER NOT NULL,
                    source_markdown_sha256 TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (
                        content_object_id,
                        extraction_artifact_id,
                        chunk_policy_id,
                        source_markdown_sha256
                    )
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    chunk_set_id TEXT NOT NULL REFERENCES cx_chunk_sets(chunk_set_id),
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    ordinal INTEGER NOT NULL,
                    start_offset INTEGER NOT NULL,
                    end_offset INTEGER NOT NULL,
                    char_count INTEGER NOT NULL,
                    text_sha256 TEXT NOT NULL,
                    text_preview TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (chunk_set_id, ordinal),
                    UNIQUE (chunk_set_id, text_sha256)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_retrieval_packages (
                    retrieval_package_id TEXT PRIMARY KEY,
                    retrieval_package_schema_version TEXT NOT NULL DEFAULT 'cx_retrieval_context_package.v1',
                    package_hash TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT NOT NULL,
                    query_text_sha256 TEXT NOT NULL,
                    query_text_preview TEXT,
                    query_embedding_provided BOOLEAN NOT NULL DEFAULT 0,
                    query_embedding_sha256 TEXT,
                    query_embedding_dimension INTEGER NOT NULL DEFAULT 0,
                    purpose TEXT NOT NULL,
                    retrieval_policy_id TEXT NOT NULL,
                    retrieval_policy_version TEXT,
                    retrieval_policy_hash TEXT,
                    retrieval_policy_source TEXT NOT NULL,
                    ranker_mix TEXT NOT NULL,
                    rerank_state TEXT NOT NULL,
                    permission_snapshot_hash TEXT NOT NULL,
                    source_summary TEXT NOT NULL DEFAULT '{}',
                    score_summary TEXT NOT NULL DEFAULT '{}',
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    no_answer_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_retrieval_evidence_items (
                    retrieval_package_id TEXT NOT NULL REFERENCES cx_retrieval_packages(retrieval_package_id),
                    evidence_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    content_version_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL REFERENCES cx_chunks(chunk_id),
                    chunk_policy_id TEXT NOT NULL,
                    source_anchor TEXT NOT NULL DEFAULT '{}',
                    citation_label TEXT NOT NULL,
                    evidence_text_sha256 TEXT NOT NULL,
                    evidence_text_preview TEXT NOT NULL,
                    final_score REAL NOT NULL DEFAULT 0,
                    scores TEXT NOT NULL DEFAULT '{}',
                    matched_terms TEXT NOT NULL DEFAULT '[]',
                    permission_result TEXT NOT NULL DEFAULT '{}',
                    neighbor_context TEXT NOT NULL DEFAULT '[]',
                    quality_flags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (retrieval_package_id, evidence_id),
                    UNIQUE (retrieval_package_id, rank)
                )
                """
            )
        )


def _create_sqlite_cx_processing_persistence_tables(engine: object) -> None:
    _create_sqlite_cx_content_retrieval_tables(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_processing_runs (
                    pipeline_run_id TEXT PRIMARY KEY,
                    pipeline_schema_version TEXT NOT NULL DEFAULT 'cx_document_processing_pipeline.v1',
                    document_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    status TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT NOT NULL,
                    job_id TEXT,
                    job_type TEXT,
                    job_status TEXT,
                    job_attempt_count INTEGER NOT NULL DEFAULT 0,
                    job_max_attempts INTEGER NOT NULL DEFAULT 0,
                    job_retryable BOOLEAN,
                    job_subject_ref TEXT NOT NULL DEFAULT '{}',
                    job_links TEXT NOT NULL DEFAULT '{}',
                    step_total INTEGER NOT NULL DEFAULT 0,
                    step_succeeded INTEGER NOT NULL DEFAULT 0,
                    step_skipped INTEGER NOT NULL DEFAULT 0,
                    step_failed INTEGER NOT NULL DEFAULT 0,
                    queued_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_processing_steps (
                    pipeline_run_id TEXT NOT NULL REFERENCES cx_document_processing_runs(pipeline_run_id),
                    step_order INTEGER NOT NULL,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_ref_type TEXT,
                    output_ref_id TEXT,
                    output_ref_document_id TEXT REFERENCES cx_content_objects(content_object_id),
                    output_ref_hash TEXT,
                    error_code TEXT,
                    error_detail_sha256 TEXT,
                    error_retryable BOOLEAN,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (pipeline_run_id, step_order),
                    UNIQUE (pipeline_run_id, step_id)
                )
                """
            )
        )


def _create_sqlite_service_jobs_table(engine: object) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_jobs (
                    job_id TEXT PRIMARY KEY,
                    job_schema_version TEXT NOT NULL DEFAULT 'common_job.v1',
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 1,
                    retryable INTEGER NOT NULL DEFAULT 1,
                    links TEXT NOT NULL DEFAULT '{}',
                    payload TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    replay_lineage TEXT,
                    available_at TEXT NOT NULL,
                    locked_at TEXT,
                    locked_by TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (job_type, idempotency_key)
                )
                """
            )
        )


def _create_sqlite_service_operational_events_table(engine: object) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_operational_events (
                    event_id TEXT PRIMARY KEY,
                    event_schema_version TEXT NOT NULL DEFAULT 'operational_event.v1',
                    service_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT,
                    subject_type TEXT,
                    subject_id TEXT,
                    message TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
        )


def _create_sqlite_service_worker_heartbeats_table(engine: object) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_worker_heartbeats (
                    service_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    heartbeat_schema_version TEXT NOT NULL DEFAULT 'worker_heartbeat.v1',
                    worker_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active_job_id TEXT,
                    trace_id TEXT,
                    started_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (service_id, worker_id)
                )
                """
            )
        )
