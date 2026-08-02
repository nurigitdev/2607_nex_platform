from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

import check_backend_service_endpoints as endpoint_smoke
import check_db_readiness as db_smoke


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
        db_smoke.psycopg,
        "connect",
        lambda database_url, connect_timeout: FakeDbConnection(),
    )

    assert db_smoke.main() == 0
    output = capsys.readouterr().out
    assert "nex-test: READY" in output
    assert "db=nex_example_dev" in output


def test_db_smoke_reports_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_connect(database_url: str, connect_timeout: int) -> FakeDbConnection:
        raise RuntimeError("down")

    monkeypatch.setattr(db_smoke, "DATABASE_ENVS", {"nex-test": "NEX_TEST_DATABASE_URL"})
    monkeypatch.setenv("NEX_TEST_DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(db_smoke.psycopg, "connect", fail_connect)

    assert db_smoke.main() == 1
    assert "connection failed" in capsys.readouterr().out
