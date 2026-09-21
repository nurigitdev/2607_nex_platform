from __future__ import annotations

import json
from pathlib import Path

import run_s93_cx_durable_ingestion_closure as closure


def test_repository_s93_closure_passes() -> None:
    result = closure.run_s93_cx_durable_ingestion_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S94"
    assert result["feature_readiness"] == (
        "CX_DURABLE_INGESTION_ORCHESTRATION_READY"
    )
    assert all(result["checks"].values())
    assert result["summary"] == {
        "evidence_count": 8,
        "passed_evidence_count": 8,
        "pipeline_step_count": 6,
        "transition_count": 10,
        "postgres_check_count": 17,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert all(result["postgres_evidence"].values())
    assert result["next_requirement"] == "S94"


def test_s93_closure_freezes_durable_ingestion_decisions() -> None:
    decision = closure._closure_decision()

    assert decision["execution_queue"] == "existing_service_jobs_job_queue"
    assert decision["orchestration_system_of_record"] == "cx_ingest_runs"
    assert len(decision["pipeline_steps"]) == 6
    assert decision["persistence_policy"] == "owner_scoped_metadata_only"
    assert decision["concurrency_control"] == "optimistic_checkpoint_version"
    assert decision["restart_model"] == (
        "read_only_plan_then_explicit_recovery"
    )
    assert decision["migration_strategy"] == (
        "versioned_sql_schema_migrations_runner"
    )
    assert decision["postgres_smoke_target"] == "nex_cx_user@nex_cx_test"
    assert decision["dgx_live_provider_required"] is False


def test_s93_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s93_cx_durable_ingestion_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["failed_checks"]


def test_s93_closure_fails_when_evidence_does_not_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        closure,
        "run_worker",
        lambda: {"status": "FAIL", "checkpoint_version": 0},
    )

    result = closure.run_s93_cx_durable_ingestion_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_deterministic_evidence_passed"] is False
    assert result["checks"]["worker_retry_recovery_closed"] is False
    assert result["checks"]["dgx_not_required"] is False


def test_s93_closure_helpers_fail_closed(tmp_path: Path) -> None:
    failed = closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private detail"))
    )
    assert failed == {
        "status": "FAIL",
        "failure_code": "evidence_builder_failed",
        "detail": "RuntimeError",
    }
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._read_text(tmp_path / "missing") == ""
    present = tmp_path / "present"
    present.write_text("ok", encoding="utf-8")
    assert closure._read_text(present) == "ok"
    assert closure._dgx_not_required(
        {"dgx_live_provider_required": False}
    ) is True
    assert closure._dgx_not_required(
        {"decision": {"dgx_live_provider_required": False}}
    ) is True
    assert closure._dgx_not_required({}) is False
    assert closure._dgx_not_required({"dgx_required": True}) is False


def test_s93_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s93_cx_durable_ingestion_closure()
    assert closure.summary_line(passing) == (
        "s93_cx_durable_ingestion_closure=pass evidence=8/8 steps=6 "
        "postgres_checks=17 next=S94"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s93_cx_durable_ingestion_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s93_cx_durable_ingestion_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
