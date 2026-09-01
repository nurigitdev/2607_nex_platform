from __future__ import annotations

import json

import pytest

import run_ae_artifact_retention_physical_purge_postgres_smoke as smoke


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0508@127.0.0.1:5432/nex_ae_test"
        ),
    }


def passing_source_evidence() -> dict[str, object]:
    return {
        "smoke_schema_version": "ae_artifact_retention_purge_postgres_smoke.v1",
        "status": "PASS",
        "service_id": smoke.SERVICE_ID,
        "profile": smoke.DEFAULT_PROFILE,
        "database_env": "NEX_AE_TEST_DATABASE_URL",
        "redacted_database_url": (
            "postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test"
        ),
        "migration": {"planned": [], "applied": [], "skipped": []},
        "retention": {
            "approval_blocked_status": "BLOCKED",
            "approval_blocked_reason": "operator_approval_required",
            "executed_selected_count": 1,
            "deleted_counts": {
                "artifacts": 1,
                "source_refs": 1,
                "versions": 1,
                "render_jobs": 1,
                "files": 2,
                "links": 4,
                "storage_files": 2,
            },
        },
        "materialized_file_count": {"before": 4, "after_execute": 2},
        "db_before": {
            "artifact_rows": 2,
            "deleted_rows": 2,
            "candidate_rows": 1,
            "file_rows": 4,
            "link_rows": 8,
            "handoff_rows": 2,
        },
        "db_after_execute": {
            "artifact_rows": 1,
            "deleted_rows": 1,
            "candidate_rows": 0,
            "file_rows": 2,
            "link_rows": 4,
            "handoff_rows": 2,
        },
        "cleanup": {"artifacts": 1, "handoffs": 2},
        "checks": {
            "metadata_only_evidence": True,
            "approval_blocked_rows_retained": True,
        },
        "live_db": True,
    }


def test_ae_artifact_retention_physical_purge_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_artifact_retention_physical_purge_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_physical_purge_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_retention_physical_purge_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_artifact_retention_physical_purge_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_physical_purge_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_retention_physical_purge_postgres_smoke_wraps_source_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke.purge_pg,
        "run_ae_artifact_retention_purge_postgres_smoke",
        lambda env: passing_source_evidence(),
    )

    evidence = smoke.run_ae_artifact_retention_physical_purge_postgres_smoke(
        smoke_env()
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["physical_purge"] == {
        "storage_adapter": "rendered_artifact_storage",
        "database_adapter": "artifact_graph_child_first",
        "storage_delete_order": "before_database_rows",
        "approval_gate": "operator_approval_required",
        "handoff_lineage_retained": True,
    }
    assert evidence["retention"]["approval_blocked_reason"] == (
        "operator_approval_required"
    )
    assert evidence["retention"]["deleted_counts"]["storage_files"] == 2
    assert evidence["checks"]["storage_adapter_deleted_files"] is True
    assert evidence["checks"]["database_adapter_deleted_artifact"] is True
    assert evidence["checks"]["approval_blocked_rows_retained"] is True
    assert evidence["live_db"] is True
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_retention_physical_purge_postgres_smoke=pass "
        "service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL"
    )
    assert "secret-0508" not in serialized


def test_ae_artifact_retention_physical_purge_postgres_smoke_reports_source_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke.purge_pg,
        "run_ae_artifact_retention_purge_postgres_smoke",
        lambda env: {
            "status": "FAIL",
            "failure_code": "configuration_invalid",
            "detail": "secret-0508",
        },
    )

    evidence = smoke.run_ae_artifact_retention_physical_purge_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "underlying_purge_smoke_failed"
    assert evidence["detail"] == "configuration_invalid"
    assert "secret-0508" not in json.dumps(evidence)


def test_ae_artifact_retention_physical_purge_postgres_smoke_reports_check_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = passing_source_evidence()
    source["retention"] = {
        **source["retention"],  # type: ignore[arg-type]
        "approval_blocked_reason": "delete_not_enabled",
    }
    monkeypatch.setattr(
        smoke.purge_pg,
        "run_ae_artifact_retention_purge_postgres_smoke",
        lambda env: source,
    )

    evidence = smoke.run_ae_artifact_retention_physical_purge_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "physical_purge_checks_failed"
    assert "operator_approval_gate_blocked" in evidence["detail"]


def test_ae_artifact_retention_physical_purge_postgres_smoke_main_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_physical_purge_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_artifact_retention_physical_purge_postgres_smoke=skipped"
        in capsys.readouterr().out
    )
