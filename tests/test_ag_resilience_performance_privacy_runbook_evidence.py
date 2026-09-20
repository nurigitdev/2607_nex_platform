from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ag_resilience_performance_privacy_runbook_evidence as evidence


def test_privacy_runbook_passes_and_exercises_failure_surfaces() -> None:
    result = evidence.run_ag_resilience_performance_privacy_runbook_evidence()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["surface_count"] == 9
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    assert result["surfaces"]["admission_rejection"]["status_code"] == 503
    assert result["surfaces"]["source_timeout"]["status_code"] == 503
    assert result["surfaces"]["pool_saturation"]["projection_status"] == (
        "ATTENTION"
    )
    assert result["surfaces"]["pool_metrics_unavailable"][
        "projection_status"
    ] == "DEGRADED"


def test_privacy_runbook_fails_without_docs_live_evidence_and_hook(
    tmp_path: Path,
) -> None:
    result = evidence.run_ag_resilience_performance_privacy_runbook_evidence(
        tmp_path
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "ag_resilience_performance_privacy_runbook_failed"
    )
    assert result["checks"]["docs_present"] is False
    assert result["checks"]["quality_gate_hook_present"] is False
    assert result["checks"]["postgres_evidence_is_complete"] is False


def test_error_capture_helpers_normalize_and_reject_success() -> None:
    captured = evidence._capture_error(
        lambda: (_ for _ in ()).throw(
            evidence.AgStablePaginationError(
                error_code="ag.resilience.pagination_cursor_invalid",
                detail="Pagination cursor is invalid.",
            )
        )
    )
    normalized = evidence._capture_source_failure(
        lambda: (_ for _ in ()).throw(
            RuntimeError(evidence.FORBIDDEN_VALUES["source_exception"])
        )
    )

    assert captured["status_code"] == 400
    assert "retry_after_ms" not in captured
    assert normalized["error_code"] == "ag.resilience.source_unavailable"
    assert evidence.FORBIDDEN_VALUES["source_exception"] not in str(normalized)
    with pytest.raises(AssertionError, match="did not fail"):
        evidence._capture_error(lambda: None)
    with pytest.raises(AssertionError, match="did not fail"):
        evidence._capture_source_failure(lambda: None)


def test_pool_and_snapshot_helpers_cover_safe_shapes() -> None:
    policy = evidence.build_ag_resilience_performance_policy({})
    engine = evidence._engine(checked_out=1, checked_in=4, overflow=-4)

    assert engine.pool.checkedout() == 1
    assert engine.pool.checkedin() == 4
    assert engine.pool.overflow() == -4
    assert evidence._healthy_admission_snapshot(policy)["rejected_total"] == 0
    assert evidence._healthy_source_snapshot(policy)["raw_errors_included"] is False
    failing_pool = evidence._Pool(
        checked_out=0,
        checked_in=0,
        overflow=0,
        fail=True,
    )
    with pytest.raises(RuntimeError, match="private-runbook-database-url"):
        failing_pool.checkedout()


def test_postgres_evidence_and_runbook_actions_are_complete() -> None:
    complete = " ".join(
        (
            "live smoke: PASS",
            "database=nex_ag_test",
            "requests=25 concurrency=4",
            "p95_ms=49.678 budget_ms=1500",
            "indexes=3",
            "migration_present=true",
            "cleaned=True",
            "event_residue=0 export_residue=0",
        )
    )

    assert all(evidence._postgres_evidence(complete).values())
    assert not any(evidence._postgres_evidence("").values())
    runbook = evidence._runbook_actions()
    assert len(runbook) == 10
    assert runbook["source_timeout"]["retryable"] is True
    assert runbook["latency_budget_exceeded"]["retryable"] is False


def test_privacy_helpers_cover_nested_values_keys_and_missing_files(
    tmp_path: Path,
) -> None:
    serialized = (
        f"x={evidence.FORBIDDEN_VALUES['database_url']} "
        f"y={evidence.FORBIDDEN_VALUES['credential']}"
    )

    assert evidence._forbidden_value_labels(serialized) == [
        "credential",
        "database_url",
    ]
    assert evidence._forbidden_key_paths(
        {
            "safe": [
                {"authorization": "redacted"},
                {"nested": {"sql": "redacted"}},
                "leaf",
            ]
        }
    ) == ["safe[0].authorization", "safe[1].nested.sql"]
    with pytest.raises(ValueError, match="forbidden values"):
        evidence._assert_no_forbidden_values(serialized)
    assert evidence._read_text(tmp_path / "missing") == ""
    assert evidence._mapping({"ok": True}) == {"ok": True}
    assert evidence._mapping(None) == {}


def test_summary_line_reports_pass_and_failure() -> None:
    passed = evidence.summary_line(
        {
            "status": "PASS",
            "surface_count": 9,
            "checks": {
                "forbidden_values_absent": True,
                "postgres_evidence_is_complete": True,
                "runbook_complete": True,
            },
        }
    )
    failed = evidence.summary_line(
        {"status": "FAIL", "failure_code": "failed"}
    )

    assert "runbook=pass" in passed
    assert "privacy=True" in passed
    assert "postgres=True" in passed
    assert "runbook=fail" in failed


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passing = {
        "status": "PASS",
        "surface_count": 1,
        "checks": {
            "forbidden_values_absent": True,
            "postgres_evidence_is_complete": True,
            "runbook_complete": True,
        },
    }
    monkeypatch.setattr(
        evidence,
        "run_ag_resilience_performance_privacy_runbook_evidence",
        lambda: passing,
    )

    assert evidence.main(["--summary"]) == 0
    assert "runbook=pass" in capsys.readouterr().out
    assert evidence.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        evidence,
        "run_ag_resilience_performance_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert evidence.main([]) == 1
