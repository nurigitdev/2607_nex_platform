from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

import run_platform_release_candidate_postgres_restart as runner
from nex_runtime.release_candidate_postgres import (
    RELEASE_CANDIDATE_POSTGRES_SCHEMA_VERSION,
    build_release_candidate_postgres_restart_evidence,
)


def passing_source() -> dict[str, object]:
    return {
        "status": "PASS",
        "service_count": 5,
        "process_count": 13,
        "process_generation_count": 2,
        "pool_count_per_generation": 10,
        "fresh_pool_count": 10,
        "migration_gate_count": 2,
        "migration_count_per_generation": 101,
        "restart_count": 1,
        "restored_count": 5,
        "cleaned_count": 5,
        "absence_count": 5,
        "evidence_record_count": 60,
        "shutdown_order": ["runtime_processes", "postgres_pools"],
        "work_claiming_enabled": False,
        "remote_provider_required": False,
    }


def test_builds_metadata_only_five_database_restart_gate() -> None:
    result = build_release_candidate_postgres_restart_evidence(
        passing_source(),
        observed_at=datetime(2026, 10, 6, 1, 2, 3, tzinfo=UTC),
    )

    assert result["schema_version"] == RELEASE_CANDIDATE_POSTGRES_SCHEMA_VERSION
    assert result["status"] == "PASS"
    assert result["failure_code"] is None
    gate = result["gate_evidence"]
    assert gate["gate_id"] == "five_database_restart"
    assert gate["actual_execution"] is True
    assert gate["private_payload_included"] is False
    assert gate["observed_at"] == "2026-10-06T01:02:03Z"
    assert gate["metrics"] == {
        "database_count": 5,
        "restored_database_count": 5,
        "cleaned_database_count": 5,
        "database_residue_count": 0,
        "process_count": 13,
        "process_generation_count": 2,
        "migration_gate_count": 2,
        "migration_count_per_generation": 101,
        "restart_count": 1,
    }
    assert len(gate["evidence_digest"]) == 64
    assert "database_url" not in json.dumps(result)


@pytest.mark.parametrize(
    ("field", "value", "check"),
    (
        ("status", "FAIL", "source_passed"),
        ("service_count", 4, "five_databases_reached"),
        ("process_count", 12, "two_process_generations_ready"),
        ("process_generation_count", 1, "two_process_generations_ready"),
        ("pool_count_per_generation", 9, "fresh_pools_created"),
        ("fresh_pool_count", 9, "fresh_pools_created"),
        ("migration_gate_count", 1, "migration_gates_passed"),
        ("migration_count_per_generation", 0, "migration_gates_passed"),
        ("migration_count_per_generation", True, "migration_gates_passed"),
        ("restart_count", 0, "restart_completed"),
        ("restored_count", 4, "all_databases_restored"),
        ("cleaned_count", 4, "all_sentinels_cleaned"),
        ("absence_count", 4, "all_sentinels_cleaned"),
        ("evidence_record_count", 59, "phase_evidence_complete"),
        ("shutdown_order", [], "runtime_stopped_in_order"),
        ("work_claiming_enabled", True, "background_claiming_disabled"),
        ("remote_provider_required", True, "remote_provider_not_required"),
    ),
)
def test_fails_closed_for_incomplete_protected_evidence(
    field: str,
    value: object,
    check: str,
) -> None:
    source = passing_source()
    source[field] = value

    result = build_release_candidate_postgres_restart_evidence(source)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "release_candidate_postgres_restart_failed"
    assert result["checks"][check] is False


def test_naive_timestamp_is_normalized_to_utc() -> None:
    result = build_release_candidate_postgres_restart_evidence(
        passing_source(), observed_at=datetime(2026, 10, 6, 1, 2, 3)
    )
    assert result["gate_evidence"]["observed_at"].endswith("Z")


def test_runner_is_opt_in_and_enables_existing_s133_smoke() -> None:
    skipped = runner.run_platform_release_candidate_postgres_restart({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgresql_execution"] is False
    assert runner.summary_line(skipped).endswith("next=1396")

    captured: dict[str, str] = {}

    def source(env):
        captured.update(env)
        return passing_source()

    result = runner.run_platform_release_candidate_postgres_restart(
        {runner.ENABLE_ENV: "1"}, restart_runner=source
    )

    assert captured[runner.SOURCE_SMOKE_ENV] == "1"
    assert result["status"] == "PASS"
    assert result["actual_postgresql_execution"] is True
    assert result["source_projection"]["absence_count"] == 5
    assert result["next_slice"] == "1397"
    assert runner.summary_line(result) == (
        "platform_release_candidate_postgres_restart=pass databases=5 "
        "restored=5 residue=0 next=1397"
    )


def test_runner_normalizes_source_failure_and_private_exception() -> None:
    failed = runner.run_platform_release_candidate_postgres_restart(
        {runner.ENABLE_ENV: "1"},
        restart_runner=lambda env: {
            "status": "FAIL",
            "failure_code": "migration_failed",
            "service_id": "nex-cx",
        },
    )
    assert failed["status"] == "FAIL"
    assert failed["source_projection"]["failure_code"] == "migration_failed"
    assert failed["source_projection"]["service_id"] == "nex-cx"
    assert failed["next_slice"] == "blocked"

    exceptional = runner.run_platform_release_candidate_postgres_restart(
        {runner.ENABLE_ENV: "1"},
        restart_runner=lambda env: (_ for _ in ()).throw(
            RuntimeError("private password")
        ),
    )
    assert exceptional["status"] == "FAIL"
    assert exceptional["source_projection"]["failure_code"] == (
        "release_candidate_postgres_restart_execution_failed"
    )
    assert "private password" not in json.dumps(exceptional)


def test_main_prints_summary_and_returns_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_postgres_restart",
        lambda: {"status": "SKIPPED"},
    )
    assert runner.main(["--summary"]) == 0
    assert "=skip" in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_postgres_restart",
        lambda: {"status": "FAIL", "gate_evidence": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
