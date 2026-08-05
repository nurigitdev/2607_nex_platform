from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

import check_backend_service_endpoints as endpoint_smoke
import check_db_readiness as db_smoke
import run_postgres_jobqueue_smoke as jobqueue_smoke
import run_postgres_operational_event_smoke as event_smoke
import run_postgres_operations_smoke_pack as operations_smoke


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

    monkeypatch.setattr(operations_smoke, "run_postgres_jobqueue_smoke", fake_jobqueue)
    monkeypatch.setattr(operations_smoke, "run_postgres_operational_event_smoke", fake_event)

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
    }
    assert "secret" not in str(evidence)
    assert operations_smoke.summary_line(evidence) == (
        "postgres_operations_smoke_pack=pass services=2 profile=test"
    )
    assert calls == [
        ("jobqueue", "nex-cx", "test"),
        ("event", "nex-cx", "test"),
        ("jobqueue", "nex-ag", "test"),
        ("event", "nex-ag", "test"),
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
