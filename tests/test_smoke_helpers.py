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
import run_ag_service_log_retention_smoke as ag_log_retention_smoke
import run_ag_service_log_retention_postgres_smoke as ag_log_retention_postgres_smoke
import check_backend_service_endpoints as endpoint_smoke
import check_db_readiness as db_smoke
import run_cx_processing_postgres_event_smoke as cx_processing_event_smoke
import run_cx_processing_postgres_jobqueue_smoke as cx_processing_smoke
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
    assert evidence["endpoint_count"] == 17
    assert all(evidence["checks"].values())
    assert evidence["counts"] == {
        "sources": 1,
        "events": 1,
        "logs": 1,
        "jobs": 2,
        "workers": 1,
        "worker_detail_events": 1,
        "trace_timeline": 5,
        "rollups": 1,
        "dashboard_degraded_sources": 0,
        "dashboard_replay_candidates": 1,
        "issue_candidates": 3,
    }
    assert ag_operations_dashboard_smoke.summary_line(evidence) == (
        "ag_operations_dashboard_smoke=pass endpoints=17 jobs=2 workers=1 "
        "events=1 logs=1 issues=3"
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
        ("cx_processing_postgres_jobqueue_smoke", "test"),
        ("cx_processing_postgres_event_smoke", "test"),
        ("ag_cross_service_observability_smoke", "test"),
    ]
    assert postgres_suite_smoke.summary_line(evidence) == (
        "postgres_test_smoke_suite=pass services=2 profile=test primary=nex-cx stages=13"
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
