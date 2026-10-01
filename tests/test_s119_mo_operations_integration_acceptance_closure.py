from __future__ import annotations

import json
from pathlib import Path

import run_s119_mo_operations_integration_acceptance_closure as closure


def test_repository_s119_closure_passes() -> None:
    result = closure.run_s119_mo_operations_integration_acceptance_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S120"
    assert result["feature_readiness"] == (
        "MO_OPERATIONS_INTEGRATION_LIVE_ACCEPTED"
    )
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 11,
        "passed_evidence_count": 11,
        "component_count": 5,
        "closed_component_count": 5,
        "source_count": 4,
        "capability_count": 3,
        "runtime_operation_count": 28,
        "contract_drift_count": 0,
        "postgres_check_count": 16,
        "live_check_count": 13,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S120"


def test_s119_closure_freezes_operations_and_quality_decisions() -> None:
    decision = closure._closure_decision()

    assert decision["traceability"] == ("MO-FR-003", "MO-FR-004")
    assert decision["sources"] == (
        "catalog",
        "readiness",
        "telemetry",
        "runtime",
    )
    assert decision["required_capabilities"] == (
        "embedding",
        "reranking",
        "generation",
    )
    assert decision["status_precedence"] == (
        "UNAVAILABLE",
        "DEGRADED",
        "UNKNOWN",
        "READY",
    )
    assert decision["operation"] == "GET /api/v1/operations-snapshot"
    assert decision["persistence"] == (
        "reuse_catalog_and_telemetry_no_snapshot_table"
    )
    assert decision["provider_models"] == (
        "Qwen3-Embedding-4B",
        "Qwen3-Reranker-4B",
        "Qwen3.5-4B",
    )
    assert decision["protected_live_required"] is True


def test_s119_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s119_mo_operations_integration_acceptance_closure(
        tmp_path
    )

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["postgres_check_count"] == 0
    assert result["summary"]["live_check_count"] == 0


def test_s119_closure_fails_when_deterministic_evidence_regresses(
    monkeypatch,
) -> None:
    monkeypatch.setattr(closure, "run_service", lambda: {"status": "FAIL"})

    result = closure.run_s119_mo_operations_integration_acceptance_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_evidence_passed"] is False
    assert result["components"]["boundary_domain_and_composition"] is False
    assert result["evidence_statuses"]["service"] == "FAIL"


def test_s119_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s119_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s119_mo_operations_integration_acceptance_closure()
    assert closure.summary_line(passing) == (
        "s119_mo_operations_integration_acceptance_closure=pass "
        "evidence=11/11 components=5/5 snapshot=4/3 operations=28 drift=0 "
        "postgres=16 live=13 next=S120"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s119_mo_operations_integration_acceptance_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        closure,
        "run_s119_mo_operations_integration_acceptance_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
