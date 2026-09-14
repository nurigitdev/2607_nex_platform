from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

import run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke as smoke


def test_live_http_postgres_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke(
        {}
    )

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "skipped" in smoke.summary_line(evidence)


def test_live_http_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert "failure=database_url_missing" in smoke.summary_line(evidence)


def test_live_http_postgres_loopback_server_records_safe_categories() -> None:
    server = smoke._LiveHttpPostgresLoopbackServer()
    server.start()
    try:
        for category in ("notification", "external_incident"):
            request = Request(
                server.endpoint_url,
                data=json.dumps({"provider_category": category}).encode("utf-8"),
                headers={"Authorization": "Bearer test-token"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                assert response.getcode() == (
                    201 if category == "external_incident" else 202
                )
        observations = server.observations()
    finally:
        server.stop()

    assert observations["request_count"] == 2
    assert observations["by_provider_category"] == {
        "external_incident": 1,
        "notification": 1,
    }
    assert observations["by_response_status"] == {"201": 1, "202": 1}
    assert observations["authorization_headers_seen"] == 2
    assert len(observations["path_hashes"]) == 1


def test_live_http_postgres_smoke_success_with_fakes(monkeypatch) -> None:
    cleanup_calls: list[dict[str, int]] = []

    class FakeEngine:
        def dispose(self) -> None:
            return None

    class FakeStore:
        def __init__(self, *_):
            self.records: dict[str, dict] = {}

        def save(self, record: dict) -> None:
            key = (
                record.get("dispatch_id")
                or record.get("escalation_id")
                or record.get("case_id")
                or "record"
            )
            self.records[str(key)] = dict(record)

        def get(self, dispatch_id: str) -> dict:
            return {"dispatch_id": dispatch_id, "dispatch_status": "SUCCEEDED"}

    class FakeLoopback:
        endpoint_url = "http://127.0.0.1:65530/dispatch/live-http-postgres"

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def observations(self) -> dict:
            return {
                "request_count": 2,
                "by_provider_category": {
                    "external_incident": 1,
                    "notification": 1,
                },
                "by_response_status": {"201": 1, "202": 1},
                "authorization_headers_seen": 2,
                "path_hashes": ["path-hash"],
            }

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0702",),
            applied=(),
            skipped=("0702",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda *_args, **_kwargs: FakeEngine())
    monkeypatch.setattr(smoke, "build_session_factory", lambda *_args: object())
    monkeypatch.setattr(smoke, "SqlAlchemyOperatorReviewCaseStore", FakeStore)
    monkeypatch.setattr(smoke, "SqlAlchemyOperatorReviewEscalationStore", FakeStore)
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationDispatchStore",
        FakeStore,
    )
    monkeypatch.setattr(smoke, "_LiveHttpPostgresLoopbackServer", FakeLoopback)
    monkeypatch.setattr(
        smoke,
        "run_dispatch_execution_worker_once",
        lambda *_args, **_kwargs: {
            "run_id": "run-0738",
            "run_status": "COMPLETED",
            "processed_count": 2,
            "succeeded_count": 2,
        },
    )
    monkeypatch.setattr(
        smoke,
        "build_operations_dashboard_snapshot_projection",
        lambda **_kwargs: {
            "operator_review_escalation_dispatches": {
                "execution_summary": {"by_http_status_code": {"201": 1, "202": 1}}
            }
        },
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *_args, **_kwargs: {
            "dispatch_count": 2,
            "provider_metadata_count": 2,
            "raw_value_leak_count": 0,
            "idempotency_leak_count": 0,
        },
    )

    def fake_cleanup(*_args, **_kwargs) -> dict[str, int]:
        cleanup = {"cases": 1, "escalations": 1, "dispatches": 2}
        cleanup_calls.append(cleanup)
        return cleanup

    monkeypatch.setattr(smoke, "_cleanup_smoke_rows", fake_cleanup)

    evidence = smoke.run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql+psycopg://nex_ag_user:secret@127.0.0.1/nex_ag_test"
            ),
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["smoke_schema_version"] == smoke.SCHEMA_VERSION
    assert evidence["loopback"]["request_count"] == 2
    assert evidence["observations"]["dispatch_count"] == 2
    assert evidence["cleanup"]["dispatches"] == 2
    assert all(evidence["checks"].values())
    assert len(cleanup_calls) == 2
    assert "live_http_postgres_smoke=pass" in smoke.summary_line(evidence)


def test_live_http_postgres_smoke_main_and_failure_paths(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda *_args: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )

    assert smoke.main(["--summary"]) == 1
    assert "failure=boom" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "off"},
    )
    assert smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_live_http_postgres_smoke_migration_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            smoke.MigrationError("migration failed")
        ),
    )

    evidence = smoke.run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: "postgresql://example"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"


def test_live_http_postgres_smoke_execution_failure_before_engine_cleanup(
    monkeypatch,
) -> None:
    stops: list[bool] = []

    class FakeLoopback:
        endpoint_url = "http://127.0.0.1:65530/dispatch/live-http-postgres"

        def start(self) -> None:
            return None

        def stop(self) -> None:
            stops.append(True)

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=(),
            applied=(),
            skipped=(),
        ),
    )
    monkeypatch.setattr(smoke, "_LiveHttpPostgresLoopbackServer", FakeLoopback)
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad db url")),
    )

    evidence = smoke.run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: "postgresql://example"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert stops == [True]


def test_live_http_postgres_smoke_redaction_failure() -> None:
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            smoke.LOOPBACK_TOKEN,
            {},
            forbidden_values=(smoke.LOOPBACK_TOKEN,),
        )
