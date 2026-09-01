from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_retention_batch_plan_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0485@127.0.0.1:5432/"
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


def test_ae_artifact_retention_batch_plan_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_artifact_retention_batch_plan_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_batch_plan_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_retention_batch_plan_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_artifact_retention_batch_plan_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_batch_plan_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_retention_batch_plan_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_artifact_retention_batch_plan_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_retention_batch_plan_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_artifact_retention_batch_plan_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0485" not in evidence["detail"]


def test_ae_artifact_retention_batch_plan_postgres_smoke_passes_with_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("0406_ae_artifact_handoff_trace_request_columns",),
            applied=(),
            skipped=("0406_ae_artifact_handoff_trace_request_columns",),
        ),
    )

    evidence = smoke.run_ae_artifact_retention_batch_plan_postgres_smoke(smoke_env())
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["batch_plan"]["plan_status"] == "READY"
    assert evidence["batch_plan"]["scheduler_status"] == "DISABLED"
    assert evidence["batch_plan"]["candidate_count"] == 2
    assert evidence["batch_plan"]["selected_count"] == 1
    assert evidence["batch_plan"]["default_selected_count"] == 2
    assert evidence["batch_plan"]["estimated_deleted_counts"]["files"] == 2
    assert evidence["db_observations"] == good_observations()
    assert evidence["materialized_file_count"] >= 6
    assert evidence["checks"]["metadata_only_evidence"] is True
    assert evidence["checks"]["default_delete_limit_selects_all_candidates"] is True
    assert evidence["live_db"] is True
    assert evidence["cleanup"] == {"artifacts": 3, "handoffs": 3}
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_retention_batch_plan_postgres_smoke=pass service=nex-ae-api"
    )
    assert "secret-0485" not in serialized
    assert "/data/nex-platform" not in serialized


def test_ae_artifact_retention_batch_plan_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    bad = good_observations()
    bad["candidate_rows"] = 0
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: bad)

    with pytest.raises(RuntimeError, match="db_candidate_rows"):
        smoke._execute_ae_artifact_retention_batch_plan_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_batch_plan_postgres_smoke_reports_execution_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_retention_batch_plan_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = smoke.run_ae_artifact_retention_batch_plan_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_artifact_retention_batch_plan_postgres_smoke_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert smoke._selected_artifact_ids(
        {"selected_candidates": [{"artifact_id": "artifact-001"}, {}]}
    ) == ["artifact-001"]
    assert smoke._metadata_only({"ok": True}, forbidden_fragments=["secret"])
    assert not smoke._metadata_only(
        {"leak": "secret"},
        forbidden_fragments=["secret"],
    )
    assert "secret-0485" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    assert smoke._database_url_password(
        "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/nex_ae_test"
    ) == "sensitive-pass"
    assert smoke._database_url_password("not-a-url") is None
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="NEX_AE_ARTIFACT_STORAGE_ROOT"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted(
            "password=sensitive-pass",
            {
                "NEX_AE_TEST_DATABASE_URL": (
                    "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/"
                    "nex_ae_test"
                )
            },
        )
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/ae/artifacts", {})

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_batch_plan_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_artifact_retention_batch_plan_postgres_smoke=skipped"
        in capsys.readouterr().out
    )
