from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

import check_backend_service_endpoints as endpoint_smoke
import check_db_readiness as db_smoke
import run_postgres_jobqueue_smoke as jobqueue_smoke


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
