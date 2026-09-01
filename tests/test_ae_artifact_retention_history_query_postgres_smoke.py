from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_retention_history_query_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0478@127.0.0.1:5432/nex_ae_test"
        ),
    }


def test_ae_artifact_retention_history_query_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_artifact_retention_history_query_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_history_query_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_retention_history_query_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_artifact_retention_history_query_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_history_query_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_retention_history_query_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_artifact_retention_history_query_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_retention_history_query_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_artifact_retention_history_query_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0478" not in evidence["detail"]


def test_ae_artifact_retention_history_query_postgres_smoke_passes_with_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("0472_ae_artifact_retention_execution_history",),
            applied=(),
            skipped=("0472_ae_artifact_retention_execution_history",),
        ),
    )

    evidence = smoke.run_ae_artifact_retention_history_query_postgres_smoke(
        smoke_env()
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["db_after"] == {
        "history_rows": 3,
        "dry_run_rows": 1,
        "execute_rows": 2,
        "succeeded_rows": 2,
        "blocked_rows": 1,
    }
    assert evidence["route_results"]["all"]["count"] == 3
    assert evidence["route_results"]["execute"]["count"] == 2
    assert evidence["route_results"]["blocked"]["count"] == 1
    assert evidence["route_results"]["invalid_mode_status_code"] == 422
    assert evidence["route_results"]["unauthorized_status_code"] == 401
    assert all(evidence["checks"].values())
    assert evidence["db_row_summaries"][0]["mode"] == "DRY_RUN"
    assert all(
        row["execution_payload_hash_present"]
        and row["execution_payload_matches_columns"]
        for row in evidence["db_row_summaries"]
    )
    assert evidence["cleanup"] == {"history_rows": 3}
    assert evidence["live_db"] is True
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_retention_history_query_postgres_smoke=pass service=nex-ae-api"
    )
    assert "secret-0478" not in serialized
    assert "/data/nex-platform" not in serialized
    assert '"execution":' not in serialized


def test_ae_artifact_retention_history_query_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_get_history",
        lambda *args, **kwargs: {"status_code": 503, "body": {}},
    )

    with pytest.raises(RuntimeError, match="route_all_ok"):
        smoke._execute_ae_artifact_retention_history_query_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_history_query_postgres_smoke_reports_execution_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_retention_history_query_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = smoke.run_ae_artifact_retention_history_query_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_artifact_retention_history_query_postgres_smoke_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    evidence = {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "PASS",
        "service_id": smoke.SERVICE_ID,
        "database_env": "NEX_AE_TEST_DATABASE_URL",
        "route_results": {"all": {"count": 3}, "blocked": {"count": 1}},
        "db_after": {"history_rows": 3},
        "cleanup": {"history_rows": 3},
        "live_db": True,
    }
    row = {
        "retention_execution_id": "execution-0478",
        "mode": "EXECUTE",
        "execution_status": "SUCCEEDED",
        "idempotency_key": "key-0478",
        "deleted_counts": {"artifacts": 1},
        "execution_payload_hash": "a" * 64,
        "execution": {
            "execution_id": "execution-0478",
            "mode": "EXECUTE",
            "execution_status": "SUCCEEDED",
        },
        "checked_at": "2026-09-01T02:50:00Z",
    }

    assert smoke._database_url_password(
        "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/nex_ae_test"
    ) == "sensitive-pass"
    assert smoke._database_url_password(None) is None
    assert smoke._database_url_password("not-a-url") is None
    assert smoke._safe_response_json(type("Response", (), {"json": lambda self: []})()) == {}
    assert smoke._metadata_only({"safe": "ok"}, forbidden_fragments=["secret"])
    assert not smoke._metadata_only(
        {"leak": "storage_ref"},
        forbidden_fragments=["storage_ref"],
    )
    assert smoke._db_row_summaries([row]) == [
        {
            "retention_execution_id": "execution-0478",
            "mode": "EXECUTE",
            "execution_status": "SUCCEEDED",
            "idempotency_key": "key-0478",
            "deleted_artifacts": 1,
            "execution_payload_hash_present": True,
            "execution_payload_matches_columns": True,
            "checked_at": "2026-09-01T02:50:00Z",
        }
    ]
    assert smoke._route_summary(
        {
            "artifact_retention_execution_history_collection_schema_version": (
                "ae_artifact_retention_execution_history_collection.v1"
            ),
            "count": 1,
            "summary": {"execute_count": 1},
            "items": [{"retention_execution_id": "execution-0478"}],
        }
    ) == {
        "schema_version": "ae_artifact_retention_execution_history_collection.v1",
        "count": 1,
        "summary": {"execute_count": 1},
        "item_ids": ["execution-0478"],
    }
    assert smoke._items({"items": ["bad", {"ok": True}]}) == [{"ok": True}]
    assert "secret-0478" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=secret-0478", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/ae/artifacts", {})
    with pytest.raises(ValueError, match="raw execution JSON"):
        smoke.assert_smoke_evidence_redacted('{"execution": {}}', {})
    assert smoke.summary_line(evidence).endswith("cleanup_history=3")

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_history_query_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_artifact_retention_history_query_postgres_smoke=skipped"
        in capsys.readouterr().out
    )
